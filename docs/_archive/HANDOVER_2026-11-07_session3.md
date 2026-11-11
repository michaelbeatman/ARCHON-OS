# HANDOVER 2026-11-07 (Session 3, Abschluss) — für die nächste Session

Projekt: Archon OS, `/mnt/raid/AgenticOS-2026` · Branch **`refactor/a5-di-config` @ `1424e3dc`**
Stand: 2026-11-07, ~21:45 · Erstellt im Auftrag von Michael Keller · Sprache: Deutsch.
Dieses Dokument **ergänzt** `HANDOVER_2026-11-07_session2.md` und `HANDOVER_2026-11-07_nacht.md`.
Es beschreibt den Stand **nach** Paket 1, Paket 2 und der Proxy-Härtung.

---

## 1. Copy-Paste für die nächste Session

```
Projekt: Archon OS, /mnt/raid/AgenticOS-2026 (Port 8501, Nur-Loopback).
Branch: refactor/a5-di-config @ 1424e3dc. NIEMALS main. Kein Push, kein Merge.

LIES ZUERST (in dieser Reihenfolge):
  docs/HANDOVER_2026-11-07_session3.md   <- dieses Dokument (Stand + offene Punkte)
  docs/GRUNDPRUEFUNG_2026-11-07.md       <- 36 Punkte nachgemessen, P1-P8, Sicherheit, tote UI
  docs/PLAN_STRUKTUR_2026-11-07.md       <- Etappenplan Paket 3 (nur Plan, nicht gestartet)
  docs/AUDIT_STATUS.md                   <- Abarbeitungsstand je Audit-Punkt
  docs/A5_INVENTUR.md                    <- Globals-Inventur

DREI PFLICHT-GUARDS nach JEDER Änderung (rot -> sofort git checkout -- <Datei>):
1) .venv/bin/python scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-07.json
     # Exit 0, Soll 585 Pfade / 861 Operationen
2) .venv/bin/python scripts/check_router_names.py; echo "exit=$?"    # exit=0 (schweigt im Erfolgsfall)
3) .venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider   # Soll 661 passed, 8 skipped

BETRIEBSREGEL: ARCHON-OS läuft mit --reload, das Repo ist rw nach /app gemountet.
Jede gespeicherte Datei ist SOFORT live. Kein Deploy nötig; ein Syntaxfehler
unterbricht die Instanz. Nach jeder Änderung: /health (200) + docker logs | grep -c Traceback (0).
```

---

## 2. Was in dieser Session passiert ist

Ausgangspunkt war ein Handover-Bericht einer Vorgänger-Session. Michael ließ gegenprüfen, dann
die benannten Defekte angehen, dann eine Grundprüfung fahren, dann Paket 1 (Quick Wins) und
Paket 2 (RBAC) umsetzen. Die Router-Session hat **jede** Behauptung nachgemessen; **fünf**
Fremdberichte waren an einzelnen Stellen falsch und wurden korrigiert (§6).

Reihenfolge: Gegenprobe → Defekt 1 → UI → Grundprüfung → Sofortmaßnahmen → metrics+RBAC-Pilot →
Paket 1 → Proxy (2 Eingriffe) → Paket 2 (Klasse A vollständig).

---

## 3. Commits dieser Session (14, alle pfadgenau und einzeln verifiziert)

| Commit | Inhalt | Umfang |
|---|---|---|
| `cfb4e615` | docs: Handover 1 korrigiert (Fork-Punkt, Zählwerte, Guard-2-Stummheit, Gegenprobe) | 1 Datei, +52/−6 |
| `ffb04bec` | fix(system): Restart-Route diagnostiziert statt startet (`request_status`, Update-Ziel, 15 Tests) | 5 Dateien, +461/−89 |
| `dec9479e` | docs: `hermes_updater`-Zeile 58→63, Defekt-1-Status | 2 Dateien, +4/−4 |
| `58572a6f` | fix(ui): Hermes-Core-Prüfung vertragskonform (Befund „toter Code" im Text) | 1 Datei, +21/−10 |
| `1b817b83` | docs: Grundprüfung 2026-11-07 | 1 Datei, +730 |
| `dc69d320` | docs(system): Begründung auf Michaels Token-Klarstellung umgestellt | 2 Dateien, +6/−5 |
| `cba725b4` | fix(metrics,security): echte Container-Metriken + RBAC-Pilot (6 Routen), 40 Tests | 4 Dateien, +627/−47 |
| `62b55d0a` | docs: Handover Session 2 | 1 Datei, +198 |
| `df5822bf` | docs: Etappenplan Struktur (Paket 3) | 1 Datei |
| `9f7b4c70` | perf(profiles,ui): Avatare materialisiert statt Base64 verdoppelt, tote DOM-Zugriffe, Proxy-Cfg + Compose-Entwurf vorbereitet, 12 Tests | 9 Dateien, +731/−61 |
| `f9a8acf5` | infra(proxy): Service zurück in `docker-compose.dev.yml`, Cfg aktiv (`EXEC=1`) | 1 Datei, +54 |
| `1a10d31b` | infra(proxy): Methoden-ACL — DELETE/PUT/PATCH gesperrt | 1 Datei, +58/−35 |
| `1424e3dc` | security(rbac): Rollenzaun Klasse A vollständig (123 Operationen), +345 Tests | 16 Dateien, +780/−112 |
| *(dieses Dokument)* | docs: Handover Session 3 + AUDIT_STATUS nachgezogen | 2 Dateien |

Vorgeschichte: `3897577a` (Handover 1) auf `e03e4649`; Branch-Wurzel `4956f518`;
Fork-Punkt **`de564278`** (Tip von `refactor/critical-hardening`; `314ea093` ist nur Vorfahr).

**Branch-Bilanz:** `main..HEAD` = **80 Commits**, `4956f518..HEAD` = **23**;
Diff gegen die Branch-Wurzel: **45 Dateien, 5008+ / 363−**.

---

## 4. Verifizierte Kennzahlen (alle selbst gemessen)

| Größe | Wert | Befehl |
|---|---|---|
| `main.py` | **11.404** Zeilen | `wc -l main.py` |
| Modul-Globals | **25** | `grep -cE '^[A-Z_][A-Z0-9_]* = ' main.py` |
| Decorator-Routen | **308** (unverändert) | `grep -cE '@app\.(get\|post\|…)\(' main.py` |
| Live-Pfade / Operationen | **585 / 861**, exit 0 | `scripts/route_parity.py --check …` |
| Router-Dateien / mit `configure` | **21 / 7** (die 21. ist `_rbac.py`, kein API-Router) | `ls archon/routers/*.py \| wc -l` |
| `Depends()` in `archon/` | **1** (`system.py:182`) | `grep -rn "Depends(" archon \| wc -l` |
| Rollenzaun-Stellen | **115** | `grep -rn "require_admin" main.py archon backend views_core.py \| wc -l` |
| Tests | **661 passed, 8 skipped** | `pytest tests/ -q` |
| Image / Container | `af26a3ee66e2` (kein Rebuild) · `ARCHON-OS` 127.0.0.1:8501 | `docker inspect` |
| Proxy | `docker-socket-proxy`, Cfg aus `deploy/docker-socket-proxy/haproxy.cfg` (ro) | `docker exec … cat /proc/1/cmdline` |
| Tracebacks | **0** | `docker logs --since 5m ARCHON-OS \| grep -c Traceback` |

---

## 5. Was jetzt nachweislich besser ist (mit Beleg)

### 5.1 Container-Metriken zeigen echte Werte (`cba725b4`)
Ursache gemessen: der Daemon antwortet bei **1,005 ms** (Median n=15), der Default-Timeout lag bei
**1,0 s** → jede Antwort wurde abgeschnitten, leerer Body wurde als „gestoppt" gedeutet.
Jetzt: Timeout 3,0 s + 5-s-Cache (Invalidierung bei Container-Aktionen), drei ehrliche Zustände
`Running`/`Stopped`/`unavailable`. Live: **10/10 `Running`**, Median **1.018 ms**, Cache-Treffer
**15 ms statt 1.185 ms**. Definitionsdifferenz zur CLI dokumentiert: API enthält den Page-Cache
(169,8 MB), `docker stats` zieht ihn ab (114,1 MB) — Rohdaten stimmen überein (Δ 0,3 MB).

### 5.2 Rollenzaun auf Klasse A vollständig (`1424e3dc`)
**123 destruktive/administrative Operationen** geschützt (vorher 6). Zentral über
`archon/routers/_rbac.py` (**fail-closed**: fehlt die Injektion → 503 + ERROR-Log), angewendet in
`main.py`, 9 Routern, `backend/operations_api.py`, `views_core.py`. **225 Klasse-B-Routen bleiben
absichtlich offen** (Kanban/Task-Status, Notizen, Chat, CRM/ERP-Pflege, eigene Einstellungen),
sonst könnte ein Nicht-Admin nicht mehr normal arbeiten. Durchlässig bleiben: `auth.enabled=false`
(Fallback-Admin), `X-Archon-Service-Token`, Session-Rolle `admin`.
Belege: 345 neue Tests (je Route operator/viewer → 403, admin → Zaun lässt durch, ohne Fachcode
via 418-Sonde); Rot-Beweis `4 failed` gegen `git archive HEAD`; Assert-Bilanz der angepassten
Tests **0/0** (nur Fixtures geändert).

### 5.3 Proxy ist jetzt eine Grenze (`f9a8acf5` + `1a10d31b`)
Der Service war aus `docker-compose.dev.yml` **verschwunden**, obwohl der laufende Container das
Label dorthin trug (ein `down` hätte ihn unersetzbar gelöscht). Wieder angelegt, Regeln aus
geprüfter Cfg statt Env-Generierung, `EXEC=1` für den Paperclip-Pfad. Danach die Methoden-Lücke:
die Methodenzeile war ein ODER, `DELETE /images/...` ging bis Docker durch (**404**) → jetzt **403**.
Selbst gemessen: `DELETE/PUT/PATCH` 403 · `restart/stop` 403 · `containers/json`, `version`,
`_ping`, `json`, `stats`, `logs` 200 · `exec` **201 → 200** · `/health` 200 · 0 Tracebacks.

### 5.4 Profile-Payload um 95,8 % kleiner (`9f7b4c70`)
Nicht die Feldauswahl war das Problem, sondern **fünf Base64-Avatare**, die als `avatar` **und**
`avatar_url` je 1,25 MB doppelt ausgeliefert wurden (= 96 % der Antwort). `/api/hermes/profiles`:
2.608.405 B → **110.685 B**, Median 69,8 → **16,6 ms**. `load_roles` warm 0,04 ms statt 40 ms Parse.
Nebenbei behoben: Uploads landeten nie unter `/static` (Pfadfehler in `profiles.py` und
`hermes_profiles.py`), deshalb blieb der Base64-Wert im YAML kleben.

### 5.5 Härtung + Ehrlichkeit
- Secret-Rechte: `data/snapshots/*/.env` (8), `gmail_token.json`, `google_token.json`,
  `credentials.json`, `paperclip/docker/.env` → **600** (vorher 666/755/664).
- Restart-Route: meldet den Core-Zustand (200/409/502) statt 500 — **startet nichts**, das ist
  Michaels Entscheidung (manuell: `docker start hermes-agent`).
- Doku-Wahrheit: „40-Punkte-Audit" ist unbelegt, es sind **36**; 17 Zahlen-/Zeilendrifts korrigiert.

---

## 6. Fremdberichte, die nachweislich falsch waren (Lehre für die nächste Session)

| Behauptung | Realität | wo |
|---|---|---|
| „abgezweigt von `314ea093`" | Fork-Punkt ist `de564278` (`merge-base`) | Handover 1 |
| Zählwerte 66/9/15 Dateien/1056+ „am HEAD" | gelten für `e03e4649`; HEAD: 67/10/16/1280+ | Handover 1 |
| „4 neue Testdateien" | **5** | Handover 1 |
| „Guard 2 prüft 20 Router per AST" | Guard schweigt; 19 Dateien geprüft | Handover 1 |
| „Klasse A 123/123, Differenz 0" | **zwei Routen fehlten**, u. a. `POST /api/governance/promptfoo/run-eval` (Container-Exec mit freiem `config_path`) — von der Router-Session gefunden und nachgezäunt | Paket 2 |
| „die Anzeige ändert sich nicht" (Avatare) | vier getrackte PNGs wurden überschrieben, `1024×677 → 262×192`; verworfen, Design-Punkt offen | Paket 1 |

**Regel daraus:** jeden Bericht nachfahren — Guards selbst fahren, Zahlen selbst zählen,
Erfolgsaussagen („Differenz 0", „alle geschützt") gegen den Code prüfen, nicht gegen den Bericht.

---

## 7. Offene Punkte, priorisiert

| Prio | Punkt | Beleg | Aufwand |
|---|---|---|---|
| 1 | **48 mehrdeutige Proxy-Operationen** (`@app.api_route` mit GET+POST gemischt) — ein Zaun im Handler würde Lesezugriffe mitsperren, braucht Methodenverzweigung | Paket-2-Bericht, von Michael auf „später" gelegt | 0,5–1 Tag |
| 2 | **`main.py:2881` ruft `api_save_hermes_profile(...)`**, das in `main.py` nicht existiert → Gate-Approve „tools_erweiterung" meldet „FEHLER bei der Ausführung" | Paket-2-Bericht, verifiziert | 15 min |
| 3 | **`/api/roles` bleibt 2,6 MB** — `roles.json` ist eine zweite Kopie derselben Base64-Avatare; derselbe Helfer bringt sie auf ~115 kB | Paket-1-Bericht §1.6 | 10 Zeilen + Gleichheitsnachweis |
| 4 | **Avatar-Materialisierung schreibt in versioniertes `static/avatars/`** → Working Tree wird beim nächsten Avatar-Abruf wieder `M` zeigen | 9f7b4c70 | Ziel: ungetrackter Ordner, eigener Schnitt |
| 5 | **B3/S1-Rest:** `backend/hermes_updater.py:63` roher `AF_UNIX`-Socket am Proxy vorbei; `main.py` ebenfalls direkt (kein `DOCKER_HOST`) | Grundprüfung §4.3, Proxy-Bericht | 3–4 h |
| 6 | **`docker-compose.hermes.yml`** liegt als validierter Entwurf — drei Entscheidungen offen: anonymes 1,8-GB-Volume, Image-Tags (ein `up` wäre ein echtes Update), drei fehlende Env-Werte | Paket-1-Bericht Teil D | 1 h + Entscheidung |
| 7 | **Token-Rotation** (Telegram) — Rechte sind gehärtet, der Wert war bis 31.10. weltlesbar | Grundprüfung §4.1 | Michael, BotFather |
| 8 | **Tote UI-Pfade:** 166 von 1640 `getElementById`-Zielen ohne DOM-Element (3 Cluster gefixt, Rest offen); 67 Funktionen ohne Aufrufer | Grundprüfung §5 | 2–4 h je Cluster |
| 9 | **Paket 3 (Struktur)** — Etappenplan liegt in `docs/PLAN_STRUKTUR_2026-11-07.md` (hermes_updater → A6-Inventur → B10 → A8 → B9), **nicht gestartet** | Plan | 1–2 Wochen |
| 10 | **P1/P3/P4 klein aber offen:** DB-Öffnung 1,25 ms, N+1 max 8 Queries (8–27 ms), 411 `fetch`-Aufrufe | Grundprüfung §3.1/§3.3/§3.4 | niedrig |

---

## 8. Rollback

- Pro Commit: `git revert <sha>`.
- **Wichtig:** `main.py` und `archon/routers/_rbac.py` gehören zusammen — ein Teil-Rollback lässt
  die Router **fail-closed** sperren (503 auf allen geschützten Router-Routen).
- Proxy: `cp <backup>/haproxy.cfg deploy/docker-socket-proxy/haproxy.cfg` + recreate
  (`docker compose -f docker-compose.dev.yml -p archon-os-dev up -d --force-recreate --no-deps docker-socket-proxy`).
  Achtung: `compose config` liefert als Projektnamen `agenticos-2026` (wg-easy) — **immer
  `-p archon-os-dev`** verwenden, sonst entsteht eine zweite Instanz.
- Kein Deploy-Rollback nötig: `--reload`, Image `af26a3ee66e2` unverändert.

---

## 9. Was NICHT belegt ist (ehrlich)

- **RBAC live mit echtem `viewer`-Konto:** kein Testkonto angelegt (Produktivdaten). Belegt sind
  Direktaufruf-Tests + Zaun-Einheitstests + Live-Gegenprobe mit Service-Token.
- **Promptfoo-Route nach dem Zaun:** nicht live aufgerufen (würde einen Container-Exec auslösen);
  belegt durch zwei neue Tests (403 für operator/viewer, Durchlass für admin).
- **Kaltstart** des Systems (ohne `--reload`): nicht geprüft.
- **Last/Nebenläufigkeit** für P1–P8: nicht gemessen.
- **Live-Erfolgsprobe der Restart-Route:** unmöglich, solange `hermes-agent` gestoppt bleibt.
- **48 Proxy-Routen** und die 225 Klasse-B-Entscheidungen: bewusst offen, oben geführt.

---
*Alle Zahlen sind selbst gemessen; wo eine Zahl zitiert ist, steht die Quelle dabei.
Branch `refactor/a5-di-config` @ `1424e3dc` · 661 passed / 8 skipped · Guards grün · Proxy gehärtet.*

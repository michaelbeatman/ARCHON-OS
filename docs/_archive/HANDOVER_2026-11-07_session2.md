# HANDOVER 2026-11-07 (Abend, Session 2) — Router-Session

Projekt: Archon OS, `/mnt/raid/AgenticOS-2026` · Branch `refactor/a5-di-config` ·
Erstellt im Auftrag von Michael Keller. Sprache: Deutsch.
Dieses Dokument **ergänzt** `docs/HANDOVER_2026-11-07_nacht.md` (Handover 1), es ersetzt es nicht.

---

## 1. Copy-Paste für die nächste Session

```
Projekt: Archon OS, /mnt/raid/AgenticOS-2026 (Docker-Port 8501, Nur-Loopback).
Branch: refactor/a5-di-config @ cba725b4. NIEMALS main. Kein Push, kein Merge.
Lies zuerst: docs/GRUNDPRUEFUNG_2026-11-07.md (36 Punkte nachgemessen, P1-P8, Sicherheit,
tote UI-Pfade), dann docs/HANDOVER_2026-11-07_nacht.md (Handover 1 + Korrektur-Abschnitt),
dann docs/AUDIT_STATUS.md und docs/A5_INVENTUR.md.

Drei Pflicht-Guards nach JEDER Änderung (rot -> sofort git checkout -- <Datei>):
1) .venv/bin/python scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-07.json
     # Exit 0, Soll 585 Pfade / 861 Operationen
2) .venv/bin/python scripts/check_router_names.py; echo "exit=$?"   # exit=0; Skript schweigt im Erfolgsfall
3) .venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider   # Soll: 298 passed, 8 skipped

WICHTIG: ARCHON-OS laeuft mit `--reload`, das Repo ist rw nach /app gemountet —
jede gespeicherte Datei ist SOFORT live. Kein Deploy noetig, aber ein Syntaxfehler
unterbricht die Instanz. Nach jeder Aenderung: /health + docker logs | grep -c Traceback.
```

---

## 2. Was in dieser Session passiert ist

Ausgangslage war ein Handover-Bericht einer Vorgänger-Session. Der Auftrag lautete: gegenlesen,
Guards nachmessen, dann die benannten Defekte angehen, danach eine Grundprüfung. Reihenfolge:

1. **Handover-Gegenprobe** (read-only) — alle drei Guards grün, alle Bestandszahlen deckungsgleich,
   **vier Dokumentfehler** gefunden (§4).
2. **Defekt 1 behoben** — `POST /api/system/hermes/restart` zielte auf einen Container `hermes`,
   den es nicht gibt (jeder Aufruf 500). Entscheidung Michaels: **melden statt starten**.
3. **UI-Text nachgezogen** — dabei festgestellt: die Funktion ist **toter Code** (kein Button im DOM).
4. **Grundprüfung in vier Blöcken** — 36 Punkte nachgemessen, P1–P8 erstmals gemessen,
   Sicherheit (S9/S4/B3), tote UI-Pfade. Eigenes Dokument, `1b817b83`.
5. **Sofortmaßnahmen** — Secret-Dateien auf 600 gehärtet (ausgeführt und verifiziert).
6. **metrics-Fix + RBAC-Pilot** — umgesetzt, mit 40 Tests und zwei Rot-Beweisen (`cba725b4`).

---

## 3. Commits dieser Session (alle pfadgenau, fremde Dateien unberührt)

| Commit | Inhalt | Umfang |
|---|---|---|
| `cfb4e615` | docs: Handover 1 korrigiert (Fork-Punkt, reproduzierbare Zählwerte, Guard-2-Stummheit, Gegenprobe) | 1 Datei, +52/−6 |
| `ffb04bec` | fix(system): Hermes-Core-Route diagnostiziert statt fälschlich neu zu starten (200 `ok` / 409 `not_running` / 409 `absent` / 502), `request_status` im Docker-Client, `hermes-dashboard` aus dem Update-Ziel, 15 Tests | 5 Dateien, +461/−89 |
| `dec9479e` | docs: `hermes_updater`-Zeile 58→63, Defekt-1-Status | 2 Dateien, +4/−4 |
| `58572a6f` | fix(ui): Hermes-Core-Prüfung vertragskonform (inkl. Befund „toter Code") | 1 Datei, +21/−10 |
| `1b817b83` | docs: Grundprüfung 2026-11-07 (730 Zeilen) | 1 Datei, +730 |
| `dc69d320` | docs(system): Begründung der Diagnose-Route auf Michaels Token-Klarstellung umgestellt | 2 Dateien, +6/−5 |
| `cba725b4` | fix(metrics,security): echte Container-Metriken + RBAC-Pilot auf 6 Routen, 40 Tests | 4 Dateien, +627/−47 |

Vorgeschichte: `3897577a` (Handover 1) auf `e03e4649`; Branch-Wurzel `4956f518`;
Fork-Punkt **`de564278`** (Tip von `refactor/critical-hardening`; `314ea093` ist nur Vorfahr).

---

## 4. Die vier Dokumentfehler aus Handover 1 (korrigiert in `cfb4e615`)

1. **Fork-Punkt** stand als `314ea093` — richtig ist `de564278` (`git merge-base` gemessen).
2. **Zählwerte** 66 Commits / 9 Branch-Commits / 15 Dateien / 1056+ galten für `e03e4649`,
   nicht für HEAD (67 / 10 / 16 / 1280+).
3. **„4 neue Testdateien"** — es sind **5**.
4. **Guard 2 schweigt im Erfolgsfall** — „20 Router per AST" ist nicht durch seine Ausgabe gedeckt
   (er prüft 19 Dateien, `__init__.py` wird übersprungen).

---

## 5. Was die Grundprüfung an der Doku-Wahrheit geändert hat

- **„40-Punkte-Audit" ist nicht belegt:** es sind **36** Punkte, seit der ersten committeten Fassung.
  Die „~40" in `AUDIT_STATUS.md:5` war eine gerundete Schätzung; über vier Handovers wurde daraus
  ein Faktum. Das externe Original-Audit liegt **nicht** im Repo — vier Punkte sind nicht
  rekonstruierbar.
- **Status Ist:** 12 ✅ / 19 🟡 / 5 🔴. Drei Punkte (P2, P7, P8) waren **schlechter dokumentiert als
  die Realität**; kein Punkt musste von ✅ auf 🔴 zurückgestuft werden.
- **17 Drifts**, davon 12 in der Punktetabelle: veraltete Zeilennummern (`Depends()` 123→182,
  `httpx.Client` 8942→8903, Sandbox-Handler 8372→8335, Rollenprüfung 7376→7298) und Zahlen
  (`archon/core` 8→10, Importe „50+"→39, A8 „15+"→26, Tests 243→258).

---

## 6. Die beiden Reparaturen aus `cba725b4` — was sie tun und was belegt ist

### 6.1 Container-Metriken (`/api/v1/container/metrics`)
**Defekt:** Der Endpunkt fragte Docker mit dem Default-Timeout **1,0 s**; der Daemon antwortet aber
bei **1,005 ms** (Median n=15, 0 Ausreißer > 2 s). Jede Antwort wurde abgeschnitten, der leere Body
als „gestoppt" gedeutet → **jeder laufende Container erschien als „Stopped, 0 %"**.

**Fix:** Timeout **3,0 s**, `@ttl_cache(seconds=5)` (Schlüssel enthält den Container-Namen,
Invalidierung bei Container-Aktionen), drei ehrliche Zustände `Running` / `Stopped` (Docker sagt es)
/ `unavailable` (Timeout, keine Aussage).

**Belegt:** 10/10 Abfragen `Running` (z. B. 0,24 % CPU, 169,8 MB); Median **1.018 ms** (vorher
1.006 ms — der Fix kauft keine Latenz, er liest vollständig); Cache-Treffer **15 ms statt 1.185 ms**
(≈78×, drei Paare). Acht Container einzeln geprüft, kein Wert-Leak.

**Bewusste Definitionsdifferenz:** API zeigt **169,8 MB**, `docker stats` **114,1 MB** — die CLI
zieht den Page-Cache (`inactive_file`) ab, die API nicht. Aus den Rohdaten nachgerechnet stimmen
beide überein (113,8 vs 114,1 MB, Δ 0,3 MB). Kein Fehler; eine Angleichung wäre ein Einzeiler,
ist aber eine Produktentscheidung.

### 6.2 RBAC-Pilot (6 von 78 Schreib-Routen)
**Defekt:** Angemeldet sein genügte für alles — ein `viewer` durfte `container/exec`,
`docker/start`, `docker/stop`, `sandbox/execute`, `system/update/apply`, `system/update/rollback`.

**Fix:** `require_admin()`-Helfer (bewusst **kein** `Depends()` → A7-Kennzahl und OpenAPI-Parität
unberührt), angewendet auf die sechs Routen; Router-Fassung **fail-closed** (fehlt die Injektion,
sperrt die Route). Durchlässig bleiben `auth.enabled=false` (Fallback-Admin),
`X-Archon-Service-Token` und Session-Rolle `admin`; gesperrt: `operator`, `viewer`, `anonymous`.

**Belegt:** 33 RBAC-Tests, Suite **298 passed / 8 skipped**. Rot-Beweis gegen den Altstand:
`14 failed, 19 passed` — die 19 grünen sind die Pfade, die vorher wie nachher durchgehen
(Admin, Service-Token, Auth aus), also **kein** neues Aussperren.

---

## 7. Offene Punkte, priorisiert (gemessen, nicht geschätzt)

| Prio | Punkt | Beleg | Aufwand |
|---|---|---|---|
| 1 | **RBAC-Rest:** 66 weitere Schreib-Routen ohne Rollenprüfung (Pilot deckt 6 ab) | Grundprüfung §4.2 | 0,5–2 Tage, nach Muster `require_admin` |
| 2 | **`/api/roles` ungecacht:** 64 ms und 2,63 MB pro Poll; `/api/hermes/profiles` 2,6 MB, p95 1,1 s | Grundprüfung §3.4/§3.5 | 1–3 h |
| 3 | **Tote UI-Pfade:** 67/1628 Funktionen ohne Aufrufer, **166** `getElementById`-Ziele ohne DOM-Element (`#view-system-settings`, ~25 `erp-f-*` → TypeError bei „Neue Firma"), `openSoulModal` doppelt definiert | Grundprüfung §5 | 2–4 h für 3 Cluster |
| 4 | **B3/S1-Rest:** `backend/hermes_updater.py:63` roher `AF_UNIX`-Socket am Allowlist-Client vorbei; repo-weit genau **zwei** AF_UNIX-Stellen | Grundprüfung §4.3 | 3–4 h Migration |
| 5 | **Proxy-Flags wirkungslos:** `ALLOW_RESTARTS=0`/`EXEC=0` greifen nicht, weil die haproxy-Regeln unankert sind (`^(/v[..])?/containers` matcht Präfixe) — `POST /containers/x/restart` erreicht Docker (404 von Docker statt 403 vom Proxy) | Defektanalyse §2A | 1–1,5 h nach Pfad-Inventar |
| 6 | **`docker-compose.hermes.yml` fehlt:** `hermes-agent` und `hermes-dashboard` sind nur per `docker start` bedienbar; jeder Recreate (echter Update-Lauf) unmöglich | Defektanalyse §2 | 1 h |
| 7 | **Token-Rotation offen** (Aufgabe Michael, BotFather) | Sicherheitsbefund §8 | — |
| 8 | **Kleinmaßnahmen:** DB-Pooling (1,25 ms/Request), N+1 (max 8 Queries, 8–27 ms), 411 `fetch`-Aufrufe beim Start | Grundprüfung §3.1/§3.3/§3.4 | niedrig |
| 9 | **Alte Wunden:** B9 50 × `api_route`, A8 26 Dateien mit verstreuter Config, A6 31 × Sync-Kandidaten, B10 145 × `/opt/data` | `AUDIT_STATUS.md` | je eigener Schnitt |

---

## 8. Sicherheit — Stand nach den Sofortmaßnahmen

- **Gehärtet (ausgeführt, per `stat` verifiziert):** `data/snapshots/*/.env` (8 Dateien, darunter das
  seit 31.10. weltlesbare `manual_20261031_154716/.env`), `gmail_token.json`, `google_token.json`,
  `credentials.json` (war 755), `paperclip/docker/.env` — alle **600**.
  `data/.archon_service_token` war bereits 600.
- **Token-Rotation steht aus** — Aufgabe von Michael. Michaels Einordnung: der Telegram-Token wird
  ausschließlich vom Telegram-Bot genutzt, niemand sonst hat Zugriff.
- **Anonymer Zugriff** ist durch den Auth-Gate geschlossen (`/api/roles` → 401 ohne Session).
- **Bleibende Lücke:** fehlendes Rollenkonzept auf 66 weiteren Schreib-Routen.

---

## 9. Was NICHT belegt wurde (ehrlich)

- **Live-Erfolgsprobe der reparierten Restart-Route** ist nicht möglich: der Core-Container ist
  gestoppt, und ein Start ist eine bewusste Entscheidung Michaels (nicht aus der UI).
- **P7 (Streaming)** hat der Engineer live belegt (200, chunked); die Router-Session konnte es nur
  bis zum 401 nachprüfen (kein Service-Token in ihrer Sitzung).
- **UI-Verhalten** für einen eingeloggten Nicht-Admin nach dem RBAC-Pilot: Buttons laufen in 403,
  der `fetch`-Catch loggt nur. Produktentscheidung, kein Codefehler.
- **Nebenläufigkeit unter Last** und **P1–P8 unter Konkurrenz**: nicht gemessen.
- **Kaltstart** (ohne `--reload`) nicht separat geprüft — für den Code irrelevant, für den Betrieb
  der erste echte Neustart abwarten.

---

## 10. Rollback

- Pro Commit: `git revert <sha>` — `cba725b4`, `dc69d320`, `1b817b83`, `58572a6f`, `dec9479e`,
  `ffb04bec`, `cfb4e615`.
- Kein Deploy-Rollback nötig: `--reload` übernimmt jede Datei sofort, Image `af26a3ee66e2`
  unverändert, Container 127.0.0.1:8501.
- Achtung bei Teil-Rollback: `require_admin` wird von `main.py` in den Router injiziert; ein
  Rollback nur einer der beiden Dateien lässt den Router **fail-closed** sperren (dann 403 auf
  `system/update/*`). Immer beide zusammen zurücknehmen.

---

## 11. Prüftiefe dieser Session

**Selbst ausgeführt (Router-Session):** alle drei Guards in jeder Runde; `pytest` gesamt
(243 → 258 → **298**); `git rev-list/merge-base/diff/log/show --name-only`; `stat` auf alle
gehärteten Dateien; `docker ps -a`, `docker inspect` (RestartPolicy, Labels, Binds, Cmd);
`docker stats --no-stream` (1,04 s real); `docker logs | grep -c Traceback`; `curl` (health, SSE,
`/api/roles`); `grep`/AST-Stichproben auf Rollenprüfungen und `require_admin`.

**Delegiert und anschließend gegengeprüft:** Gegenprobe, Defektanalyse, Umsetzungen, Grundprüfung
(Profil `senior_fullstack_engineer`, `openrouter/deepseek-v4.1-flash-1017`). `executive_decision_architect`
war wegen Free-Tier-Cooldown (HTTP 429) nicht einsetzbar.

**Nicht selbst gemessen:** Live-Latenz der Metriken (Engineer: n=10), Cache-Treffer, Rot-Beweise
(Engineer: echte Läufe gegen `git show HEAD:…`) — in den Commit-Nachrichten und diesem Dokument
zitiert, nicht vom Router nachgefahren.

---
*Alle Zahlen sind selbst gemessen; wo eine Zahl zitiert ist, steht die Quelle dabei.
Branch `refactor/a5-di-config` @ `cba725b4`, 298 passed / 8 skipped, Guards grün.*

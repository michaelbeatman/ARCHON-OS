# Watchdog-Supervisor-Assessment (24.11.2026) — Archon OS v0.5.7.6

**Frage:** Ist ein externer Watchdog-Supervisor (zweiter Prozess/Container außerhalb des 30-s-Loops, der den Watchdog selbst überwacht und bei Stall/Hang Alarm/Restart auslöst) tatsächlich nötig, oder erfüllt die vorhandene Infrastruktur den 24/7-Anspruch schon?

**Kurzurteil:** **Bedingt.** Es gibt eine reale, heute ungeheilte Fehlerklasse („Prozess lebt, Supervisionslogik lebt nicht"), aber die minimal sinnvolle Lösung ist **kein zweiter monolithischer Watchdog-Prozess**, sondern (1) Verdrahtung des bereits vorhandenen Dead-Man-Switch an einen echt externen Empfänger, (2) Loop-Liveness in `/livez` und erst dann (3) ein schlanker Autoheal auf Basis dieser Signale.

---

## 1) Scope / Methodik

- **Scope:** Reine Lektüre im Working Tree von `C:\.Antigravity-projekte\AgenticOS-2026` (main). Keine Code-Änderungen, keine Commits, keine Runtime-Tests.
- **Quellen:** `watchdog_daemon.py`, `main.py`, `backend/fleet_self_healing.py`, `backend/deadlock_supervisor.py`, `backend/metrics_collector.py`, `backend/process_lock.py`, `backend/graceful_shutdown_coordinator.py`, `docker-compose.yml`, `.env.example`, `ansible/roles/archon_node/**`, `config/prometheus/**`, `archon/routers/guardian.py`, `scripts/gateway_watchdog.sh`, sowie die Audit-Berichte `2026-11-24_d10_hardening.md` und `2026-11-24_FIX_WAVEN_STATUS.md`.
- **Methodik:** Volltextsuche nach Supervision-/Heartbeat-/Restart-Begriffen (`heartbeat`, `livez`, `autoheal`, `ARCHON_HEARTBEAT_WEBHOOK_URL`, `restart:`, `healthcheck`, `profiles:`, `WatchdogSec`, `alert_dispatch_loop`, `touch_heartbeat`), anschließend gezielte Lektüre der Treffer mit Zeilenbezug. Kommentare wurden nicht als Beleg gewertet, sondern nur der tatsächliche Code/Docker-Config.
- **Abgrenzung:** Externer Betrieb (Host-Cron, Uptime-Kuma-Instanz, Healthchecks.io, systemd, Prometheus-Alertmanager) wurde nicht live geprüft; Aussagen über Default-Verhalten stammen aus der kommitierten Config.

---

## 2) Ist-Zustand der Supervision

| Ebene | Mechanismus | Beleg | Was er leistet |
|---|---|---|---|
| Watchdog-Thread | `WatchdogDaemon.run_forever()`, 30 s, Log-Wachstum + `total_tokens` pro Datei, Kill-Switch via Hermes-Abort-Endpunkte, lokale `alarms.json`, n8n-Webhook | `watchdog_daemon.py:29-39`, `:239-308`, `:324-351`, `:354-360` | Erkennt Endlosschleifen-/Kostenindikatoren **im Log**, bricht Profile ab. Überwacht **keine** Prozesse, keine Threads, keine Loops. |
| Start/Stop Watchdog | Daemon-Thread (`daemon=True`) im selben Prozess, Start als erster Lifespan-Hook, Stop im Shutdown-Hook | `watchdog_daemon.py:357`; `main.py:807-822`, `:2334-2342`, `:2344-2355` | Kein Separatprozess, kein Restart bei Thread-Tod. |
| 30-s-Async-Loop | Deadlock-/Stagnations-Check, Synthese-Recovery, Alerting (`check_and_dispatch_alerts_now()` → `touch_heartbeat()`), Backpressure, Hash-Ketten | `main.py:1135-1240`, insbesondere `:1176-1184`, `:1240` | Einziger **Schreiber** des Prozess-Heartbeats. |
| 120-s-Fleet-Loop | Container-Check via Docker-Socket-Proxy, Neustart „unhealthy", Selbst-Check + Dead-Man-Switch-POST | `main.py:1258-1282`; `backend/fleet_self_healing.py:260-328`, `:300-314` | Heilt **andere** Container, prüft Staleness des eigenen 30-s-Loops, sendet Webhook. |
| Heartbeat/Dedup | `_LAST_HEARTBEAT_TS` (Prozess-Global), `report_external_alert()`, TTL/Dedup | `backend/metrics_collector.py:50-54`, `:135-169`, `:433-442` | In-Process-Zustand; `alert_dispatch_loop()` (`:445-455`) ist definiert, aber **nirgends gestartet** (Volltextsuche). |
| Deadlock-Supervisor | Leases, `last_heartbeat_at`, fail-closed PID+Heartbeat-Prüfung, Stagnations-Reset | `backend/deadlock_supervisor.py:54`, `:66-97`, `:126-197`, `:199-340` | Task-Ebene, nicht Prozess-/Loop-Ebene. Erkennt keinen Hang des Event-Loops. |
| Probes | `/livez` (nur „Prozess antwortet"), `/readyz` (DB/Config/optional Dependencies), `/health` = `/readyz` | `main.py:590-593`, `:602-654`, `:657-663` | `/livez` ist die einzige echte Liveness, wird aber **von niemandem konsumiert** (keine K8s-Manifeste, kein Docker-Healthcheck darauf). |
| Docker | `restart: unless-stopped`, Healthcheck auf `/health` (30 s/5 s/3), `depends_on: service_healthy` | `docker-compose.yml:25-50`, `:128-133` | Restart bei **Prozess-Exit**; `unhealthy` führt in Compose **nicht** zum Restart. |
| Externe Monarchie (optional) | Prometheus `up{job="archon-os"}==0` → Alertmanager, Uptime-Kuma | `config/prometheus/prometheus.yml:21-24`, `alerts.yml:151`; `docker-compose.yml:699-711` (Profil `monitoring`) | Nur **Alarm**, kein Restart; Profile standardmäßig **nicht** aktiv. |
| Graceful Shutdown | Drain/Checkpoint/WAL-Flush, `auto_resume_on_startup()` | `backend/graceful_shutdown_coordinator.py:367-391`, `:395-445`; `main.py:1765-1771` | Sauberer Exit/Recovery — **keine** Supervision. |

**Was bereits gefixt ist (nicht erneut als Lücke gewertet):** Der Deploy-Pfad wurde auf `docker-compose.yml` + `/readyz`-Gate umgestellt (`ansible/roles/archon_node/vars/main.yml:44-45`, `tasks/main.yml:97-126`); `ARCHON_HEARTBEAT_WEBHOOK_URL` ist dokumentiert und in `.env.example:121` vorhanden; der `import threading`-Fehler im Watchdog-Stop ist behoben (`watchdog_daemon.py:12`, `:310-322`); der `NameError` im Stop-Hook ist behoben (`main.py:2344-2355`). Siehe `audit_reports/2026-11-24_FIX_WAVEN_STATUS.md:30,45` und `2026-11-24_d10_hardening.md:98`. Der externe Supervisor fehlt laut `:45` ausdrücklich weiterhin.

---

## 3) Konkrete Schutzlücken mit Datei:Zeile

| # | Fehlerklasse / realistisches Szenario | Code-Bezug | Heute unbeobachtet? |
|---|---|---|---|
| L1 | **Event-Loop-Hang bei lebendigem Prozess.** Ein blockierender Sync-Call im Event-Loop (z. B. `sqlite3 BEGIN IMMEDIATE` ohne `to_thread`, oder ein LLM-Call ohne Timeout) friert 30-s- und 120-s-Loop ein. `/livez` antwortet nicht mehr, `/health` wird `unhealthy`. Docker restartet **nicht** (nur bei Exit), der In-App-Self-Healing-Check läuft im eingefrorenen Prozess. | `docker-compose.yml:32,128-133`; `main.py:590-593`, `:1139-1240`, `:1267-1282`; `fleet_self_healing.py:300-307` | **Ja** (außer Prometheus `up==0`, falls Profil `monitoring` aktiv — dann nur Alarm). |
| L2 | **Tod des Watchdog-Threads.** `run_forever()` fängt Exceptions nur um `scan_logs_and_metrics()` (`:326-330`). Jede Ausnahme außerhalb (Oracle-Thread-Start `:347`, `_stop_event.wait()` `:350`, Logging `:325`) beendet den Thread still; es gibt kein `try/finally`-Signal und keinen Neustart. Der Selbst-Check prüft nur den Heartbeat des **Async**-Loops, nicht den Watchdog-Thread. | `watchdog_daemon.py:324-351,357`; `main.py:807-822`; `fleet_self_healing.py:119-142` | **Ja** — `self_heartbeat: ok`, `/livez: alive`, keine Meldung. |
| L3 | **Supervisions-Loop startet gar nicht.** `exclusive_loop()` gibt bei nicht verfügbarem SQLite-Lock `None` zurück; der Fleet-/Deadlock-Loop läuft nie (z. B. zweite Replica während Rolling Deploy). `/health` ist trotzdem 200, kein Loop-Heartbeat, kein Dead-Man-Ping. | `backend/process_lock.py:101-117`; `main.py:1135,1258,1303-1304` | **Ja** — nur `logger.error` im Lokallog. |
| L4 | **Background-Task stirbt und wird nicht neu gestartet.** Der `done_cb` loggt nur `Unhandled exception`; die Registry wird bereinigt, es gibt keinen Respawn und keinen Liveness-Abgleich. | `main.py:1101-1132` | **Ja**. |
| L5 | **Dead-Man-Switch ist im Standard-Deploy funktionslos.** `ARCHON_HEARTBEAT_WEBHOOK_URL` steht nicht in `docker-compose.yml:55-105` → wird nicht in den Container injiziert. `.env.example:121` ist leer, `guardian.py:712` defaultet `""`; `_post_heartbeat_webhook()` ist dann No-op (`:83-87`). `dead_man_switch_configured: false` wird nur geloggt (`:309-314`), kein Fail-Fast. Uptime-Kuma liegt hinter Profil `monitoring` (`:705`), wird per Ansible nicht gestartet (`tasks/main.yml:99`). | `docker-compose.yml:55-105,705`; `.env.example:121`; `archon/routers/guardian.py:712`; `fleet_self_healing.py:60-87,309-314` | **Ja** — kein externer Empfänger, kein Alarm. |
| L6 | **In-Process-Heartbeat allein ist kein Dead-Man-Switch.** `touch_heartbeat()` wird ausschließlich vom 30-s-Loop geschrieben (`main.py:1180` → `metrics_collector.py:438`); der Staleness-Check läuft im 120-s-Loop desselben Prozesses (`fleet_self_healing.py:302`, `:119-142`). Fällt der ganze Prozess-/Event-Loop aus, fallen Sender **und** Prüfer gleichzeitig aus. Genau der Originalbefund `2026-11-24_d10_hardening.md:25` ist damit weiterhin aktuell. | `metrics_collector.py:161-169,433-442`; `main.py:1176-1184`; `fleet_self_healing.py:119-142,300-307` | **Ja**. |
| L7 | **Falscher Kandidat für Auto-Restart: `/health` ist Readiness.** `/health` ruft `readiness_check()` auf (DB-Schreibtest, Config, bei `ENVIRONMENT=production` auch OmniRoute/n8n-Probes). n8n läuft nur mit Profil `automation` (`:211`) → Dependency-Ausfall markiert den Core `unhealthy`, obwohl er gesund ist. Ein Autoheal auf `/health` würde unnötig restarten. | `main.py:602-663`; `docker-compose.yml:128-133,211` | Designfalle für die Lösung. |
| L8 | **Restart über Proxy ist nicht trivial.** `ALLOW_RESTARTS=0`, `ALLOW_START=1`, `ALLOW_STOP=1` → ein externer Autoheal darf nicht `/restart` aufrufen, nur Stop+Start; `ALLOW_RESTARTS=1` wäre eine ACL-Erweiterung. Der vorhandene Host-Watchdog (`scripts/gateway_watchdog.sh`) überwacht nur `hermes-webui` und ist nicht verdrahtet (kein Cron-Eintrag im Repo). | `docker-compose.yml:280-295`; `backend/fleet_self_healing.py:179-190`; `scripts/gateway_watchdog.sh:1-16` | Umsetzungsdetail mit Sicherheitswirkung. |

**Greifen die vorhandenen Ersatzmechanismen?**
- `restart: unless-stopped`: **nur bei Prozess-Exit**, nicht bei `unhealthy` → L1 nicht gelöst.
- Docker-Healthcheck: erkennt L1 (nach ~90 s), **restartet aber nicht** → L1 nur erkannt, nicht geheilt; L2–L4 gar nicht erkannt (thread-/task-lokal, `/livez` bleibt grün).
- Externe Heartbeat-Webhooks: **im Code vorhanden, im Deploy nicht aktiv** (L5) und selbst bei Aktivierung nur Alarm, kein Restart.
- Prometheus/Alertmanager: erkennt L1 über `up==0`, aber nur im optionalen `monitoring`-Profil und nur als Alarm.
- Fazit: **Erkennung teilweise, automatische Wiederherstellung nicht.** Der 24/7-Anspruch ist ohne externe Instanz nicht eingelöst (deckungsgleich mit `d10_hardening.md:24-26,62,108`).

---

## 4) Optionen mit Aufwand / Risiko

### Option A — Externer Dead-Man-Switch (nur Alarm), gegen `/livez` bzw. Heartbeat-Webhook
- **Inhalt:** `ARCHON_HEARTBEAT_WEBHOOK_URL` in `docker-compose.yml:55-105` durchreichen, echten Empfänger setzen (Healthchecks.io oder Uptime-Kuma-Push, erwartetes Intervall 5 min, Grace 5 min). Alarmroute geht über bestehendes Alertmanager/Telegram. Optional Docker-Healthcheck auf `/livez` umstellen, um L7 zu vermeiden.
- **Aufwand:** 2–4 h (halber Tag), überwiegend Config + Deployment + Alarmtest.
- **Risiko:** **niedrig**. Kein Code-Change, kein Restart-Pfad. Typische Fehler: HMAC-Secret fehlt, Alert bei geplanten Restarts/Drain (Grace nötig), falsches Intervall (120-s-Drossel in `fleet_self_healing.py:41,90` beachten).
- **Deckt:** L5, L6, L1-Alarm. **Nicht:** automatischen Restart, L2/L3/L4 Detektion auf Loop-Ebene.

### Option B — Loop-Liveness in `/livez` + schlanker Autoheal-Container
- **Inhalt:** (1) `touch_heartbeat()`-Äquivalente für Watchdog-Thread, 30-s- und 120-s-Loop (Timestamps + `last_seen`) in `/livez` ausgeben; `done_cb`/`exclusive_loop`-Failures als `stale` markieren. (2) Winziger Container oder Host-Cron (alle 30–60 s) prüft `/livez`, akzeptiert nur `alive + alle loop_last_seen frisch`; nach z. B. 5 aufeinanderfolgenden Fehlschlägen `docker stop` + `docker start ARCHON-OS` über Socket-Proxy (`ALLOW_START/STOP=1` reicht, **kein** `ALLOW_RESTARTS=1` nötig). Gate: `graceful_shutdown_coordinator.is_draining()` (`backend/graceful_shutdown_coordinator.py:45-46`), sonst kein Restart during Drain/Backup. Cooldown/Backoff (z. B. 15 min) gegen Restart-Storm.
- **Aufwand:** 1–2 Arbeitstage inkl. Chaos-Test (Watchdog-Thread töten, Loop-Lock blockieren, Event-Loop blockieren).
- **Risiko:** **mittel** (falsch-positive Restarts, Split-Brain mit `exclusive_loop`-Locks, Proxy-ACL, Eingriff in Drain-Fenster). Durch Cooldown + Drain-Gate + Stop-vor-Start beherrschbar.
- **Deckt:** L1–L5 (Alarm **und** Heilung).

### Option C — systemd `WatchdogSec=` oder Kubernetes `livenessProbe`
- **Inhalt:** systemd-Service mit `WatchdogSec=60s` + `sd_notify(WATCHDOG=1)` aus dem Prozess (nur Non-Docker), oder K8s-Manifeste mit `startupProbe/livenessProbe(/livez)` + `readinessProbe(/readyz)`.
- **Aufwand:** 2–4 Tage; K8s bedeutet neuen Deployment-Pfad, systemd bedeutet Bruch mit dem Ansible/Docker-Zielbild.
- **Risiko:** **hoch** — der produktive Deploy-Pfad ist heute Docker Compose (`ansible/.../vars/main.yml:44`). Keine gleichzeitige Migration mit der Supervision empfehlenswert.
- **Deckt:** L1, aber nicht L2–L4 ohne zusätzliche Loop-Signale.

---

## 5) Eindeutige Empfehlung

**Bedingt ja.** Ein externer Supervisor ist nötig, weil die konkrete Lücke „Prozess/Event-Loop hängt, Supervisionslogik läuft nicht, Docker restartet nicht, Dead-Man-Switch ist nicht verdrahtet" echt ist und den 24/7-Anspruch heute falsch erscheinen lässt. **Aber:** Es braucht keinen zweiten, eigenständigen Watchdog-Prozess mit eigener Erkennungslogik. Die minimal sinnvolle Form ist **Option A + der Liveness-Teil von Option B zuerst**, danach der Autoheal. Ohne Autoheal bleibt nur „Alarm, keine Heilung" — dann sollte der 24/7-Anspruch entsprechend abgeschwächt werden.

**Reihenfolge (was zuerst zu tun ist):**
1. `ARCHON_HEARTBEAT_WEBHOOK_URL` im Compose-Service injizieren und einen realen externen Empfänger konfigurieren; `dead_man_switch_configured == false` in Produktion als Startfehler (Fail-Fast) behandeln (heute nur Warnung, `fleet_self_healing.py:309-314`).
2. `/livez` um Loop-Freshness erweitern (Watchdog-Thread, 30-s-, 120-s-Loop; Task-Exception/Lock-Fehler → `stale`) und Docker-Healthcheck von `/health` auf `/livez` umstellen (L7 vermeiden). `/readyz` bleibt Readiness.
3. Erst danach Autoheal mit Cooldown + Drain-Gate aktivieren und im Chaos-Test verifizieren.

**Nicht empfohlen:** ein zweiter Python-Watchdog, der dieselben Logs scannt und dieselben kill-switches aufruft — das dupliziert Logik, erzeugt doppelte Aborte und löst L2/L3 nicht ohne Loop-Signale.

---

## 6) Minimal-Plan (falls empfohlen)

| Schritt | Änderung | Aufwand | Risiko |
|---|---|---|---|
| M1 | `docker-compose.yml:55-105`: `- ARCHON_HEARTBEAT_WEBHOOK_URL=${ARCHON_HEARTBEAT_WEBHOOK_URL:-}` ergänzen; `.env` mit echtem Push-Endpunkt (Healthchecks.io/Uptime-Kuma) befüllen; HMAC-Secret prüfen. Test: 120-s-Zyklus → Empfänger sieht Pings; Empfänger alarmiert bei absichtlich ausbleibendem Ping. | 2 h | niedrig |
| M2 | `main.py:590-593`: `/livez` liefert zusätzlich `loops: {watchdog, deadlock_30s, fleet_120s}` mit `last_seen`; `watchdog_daemon.py:324-351` schreibt `last_seen` am Loop-Anfang; `main.py:1121-1131` + `process_lock.py:105-111` markieren Fehlschläge. `docker-compose.yml:129` Healthcheck auf `/livez` umstellen. | 4–6 h | niedrig/mittel |
| M3 | Autoheal (Host-Cron oder Container, nur `ALLOW_START/STOP=1`): GET `/livez` alle 30 s; 5 Fehlschläge → `is_draining()`-Gate → `docker stop`, `docker start`, 15-min-Cooldown, Audit-Event. Kein `ALLOW_RESTARTS=1`, kein Regeln der App-Interna. | 4–8 h | mittel |
| M4 | Chaos-Tests: (a) Watchdog-Thread beenden, (b) `exclusive_loop`-Lock blockieren, (c) Event-Loop 3 min blockieren → jeweils Alarm + (ab M3) Restart mit Cooldown nachweisen. | 2–4 h | niedrig |

**Gesamtaufwand M1+M2 (+M3): ca. 1–2 Arbeitstage; M3 allein ca. 1 Tag.** **Risiko gesamt: niedrig bis mittel.**

### Auf KEINEN FALL gleichzeitig anfassen
- `restart: unless-stopped` / Healthcheck-Intervall- und `retries`-Schwellen / Autoheal-Restart-Schwelle **nicht gleichzeitig** ändern (nicht zuordenbare Restart-Storms).
- `/health` → `/livez`-Umstellung nicht gleichzeitig mit Aktivierung des Autoheal ohne vorherigen Alarmtest (sonst Restart statt Alarm bei Dependency-Ausfall, L7).
- Die internen 30-s-/120-s-Loops und `exclusive_loop`-Locking nicht im selben Deployment ändern wie den Autoheal (Split-Brain: neuer Prozess hält kein Lock, Suppression bleibt still).
- `graceful_shutdown_coordinator`/Drain-Fenster nicht anfassen, solange der Autoheal kein Drain-Gate hat (Checkpoint-Verlust).
- Docker-Socket-Proxy-ACL (`ALLOW_RESTARTS=0`, `ALLOW_START/STOP=1`) und `read_only`/`cap_drop`-Härtung nicht zusammen mit M3 erweitern; minimaler Eingriff ist Stop+Start über bestehende Rechte.
- Dead-Man-Ziel-URL und HMAC-Signatur nicht gleichzeitig mit dem Exclusive-Loop-Verhalten testen — sonst ist im Fehlerfall nicht unterscheidbar, ob Sender, Empfänger oder Loop fehlte.

---

**Bezug zum Ursprungsbefund:** `audit_reports/2026-11-24_d10_hardening.md:24-26` (Befunde 2–4), `:62,108` (Priorisierung „Unabhängige Supervision einführen"); `audit_reports/2026-11-24_FIX_WAVEN_STATUS.md:45` („Ein echter Watchdog-Supervisor außerhalb des überwachten 30-s-Loops fehlt weiterhin"). Diese Assessment bestätigt den offenen Punkt und konkretisiert ihn um L5 (Webhook im Default-Deploy nicht injiziert), L7 (`/health` als Readiness ist kein Autoheal-Signal) und L8 (Proxy-ACL erlaubt Stop+Start, nicht Restart).

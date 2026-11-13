# docker-socket-proxy — korrigierte Regeln (Vorbereitung, NICHT angewendet)

Stand: 2026-11-07, Paket 1 Teil C. Branch `refactor/a5-di-config`.
Basis: `docs/HANDOVER_2026-11-07_session2.md` §7 Prio 5, `docs/GRUNDPRUEFUNG_2026-11-07.md` §4.3.

Diese Datei ist **Vorbereitung**. Es wurde nichts kopiert, verlinkt, neu gestartet
oder neu gebaut. `haproxy.cfg` hier ist die geprüfte Soll-Fassung; die laufende
Datei im Container (`/tmp/haproxy.cfg`) ist unverändert.

## 1. Der Defekt, gemessen

Die laufende Datei matcht Präfixe:

```
http-request allow if { path,url_dec -m reg -i ^(/v[\d\.]+)?/containers } { env(CONTAINERS) -m bool }
```

`CONTAINERS=1` gilt damit für **jeden** Pfad unter `/containers` — auch für
`restart`, `stop`, `kill`, `exec`. Die Flags `ALLOW_RESTARTS=0`, `ALLOW_STOP=0`,
`EXEC=0` sind dadurch wirkungslos.

Gemessen gegen den laufenden Proxy (aus `ARCHON-OS` heraus, 2026-11-07):

| Aufruf | Heute | Bedeutung |
|---|---|---|
| `GET /_ping` | 200 | legitim |
| `GET /version` | 200 | legitim |
| `GET /containers/json?all=true` | 200 | legitim |
| `GET /secrets` | 403 | Sperre greift, wenn das Präfix nicht passt |
| `POST /containers/archon-xyz-does-not-exist/restart` | **404** | **erreicht Docker** (Proxy hätte 403 liefern müssen) |
| `POST /containers/archon-xyz-does-not-exist/stop` | **404** | **erreicht Docker** |
| `POST /containers/archon-xyz-does-not-exist/exec` | **404** | **erreicht Docker** (nur die Erstellung) |
| `POST /exec/abc/start` | 403 | Start ist gesperrt — deshalb heute **keine** Codeausführung über den Proxy, nur die halbe Lücke |

Konsequenz: Ein kompromittierter Client im Docker-Netz kann **Container
stoppen/neu starten** (Denial of Service, Neustart mit geändertem Zustand),
obwohl die Flags das ausdrücklich verbieten. Exec-Erstellung allein führt nichts
aus; sie ist trotzdem ein offener Pfad, der mit einem einzigen weiteren Fehler
zur Ausführung wird.

## 2. Was sich in der Soll-Fassung ändert

Nur die Regeln, die ein eigenes Flag haben, werden **verankert** (`$`):

| Namespace | vorher | jetzt |
|---|---|---|
| `/containers` | Präfix (alles) | exakt: `/containers/json`, `/containers/{id}/json`, `…/logs`, `…/stats` |
| Aktionen | `(stop|restart|kill)` ohne Anker, aber vom Präfix geschluckt | `…/(restart|stop|kill)$`, `…/start$`, `…/stop$`, `…/pause$`, `…/unpause$` — je eigenes Flag |
| Exec | `/containers/{id}/exec` über Präfix erlaubt, `/exec/{id}/start` gesperrt | beide Enden an `EXEC` |
| `_ping`, `version`, `info`, `events` | Präfix | exakt (`…/_ping$`, `…/version$`, …) |
| `images`, `networks`, `volumes`, `tasks`, `services`, `system`, … | Präfix | `…(/.*)?$` — Subtree bleibt, weil das Flag den ganzen Namespace meint |

`stop` bleibt wie im Original zusätzlich unter `ALLOW_RESTARTS` (Upstream-Semantik
von `tecnativa/docker-socket-proxy`), damit ein gesetztes `ALLOW_RESTARTS=1`
nicht plötzlich weniger darf als vorher.

## 3. Pfad-Inventar — was weiter funktionieren muss

Grundlage ist die Allowlist in `utils/docker_client.py:26-35` (der Vertrag) plus
alle realen Aufrufstellen.

| Pfad | Methode | Flag | Aufrufstelle |
|---|---|---|---|
| `/_ping`, `/version` | GET | `PING`, `VERSION` | `archon/routers/system.py:158` (Health) |
| `/containers/json` | GET | `CONTAINERS` | `main.py:947` (`?all=true`), `main.py:8469` (Fallback-Zählung), `utils/docker_client.py:32` |
| `/containers/{id}/json` | GET | `CONTAINERS` | `archon/routers/system.py:77`, `main.py:8831`, `main.py:8878`, `utils/docker_client.py:29` |
| `/containers/{id}/logs?tail=…` | GET | `CONTAINERS` | `main.py:8578`, `main.py:8611`, `main.py:8671` |
| `/containers/{id}/stats?stream=false` | GET | `CONTAINERS` | `main.py:8754`, Test `tests/test_container_metrics_states.py:36` |
| `/containers/{id}/exec` | POST | `EXEC` | `main.py:2528` (archon-quartz), `main.py:8847`, `main.py:8894`, `backend/post_task_pipeline.py:522` |
| `/exec/{id}/start` | POST | `EXEC` | `main.py:2534`, `main.py:8857`, `main.py:8904`, `backend/post_task_pipeline.py:526` |
| `/containers/{id}/start\|stop\|restart` | POST | `ALLOW_START`, `ALLOW_STOP`, `ALLOW_RESTARTS` | `main.py:1025` (`post_docker_container_action`), `main.py:1032` (hermes-dashboard-proxy), `main.py:9259` (Route), `utils/docker_client.py:34` |
| `/events` | GET | `EVENTS` | `backend/`-Events-Stream (Backend `docker-events`, `timeout server 0`) |

Tests, die die Allowlist festschreiben (nicht den Proxy): `tests/test_docker_client.py:11-25,77-80`,
`tests/test_critical_hardening.py:94-99`. Sie bleiben unverändert gültig, weil die
Allowlist nicht angefasst wurde.

**Wichtig für die Risikobewertung:** Der laufende `ARCHON-OS` hat **kein**
`DOCKER_HOST` gesetzt (`docker inspect … | grep DOCKER_HOST` → leer) und mountet
`/var/run/docker.sock` direkt. Der gesamte `main.py`-Pfad spricht also **am Proxy
vorbei** mit dem Daemon. Über den Proxy gehen heute nur:
`backend/post_task_pipeline.py:522,526` (httpx, paperclip-exec) und die
Health-Probe. Die Compose-Dateien (`docker-compose.yml:29,153`,
`docker-compose.archon.yml:55`) setzen `DOCKER_HOST=tcp://docker-socket-proxy:2375`
— dort wäre der Proxy im Pfad.

## 4. Negativtest (auszuführen **nach** der Anwendung)

```
docker exec ARCHON-OS curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST -H "Content-Type: application/json" \
  -d '{"Cmd":["true"],"AttachStdout":false,"AttachStderr":false}' \
  http://docker-socket-proxy:2375/containers/archon-xyz-does-not-exist/exec
```

- **Heute:** `404` (Docker antwortet → Proxy hat durchgelassen).
- **Soll:** `403` (Proxy lehnt ab, Docker sieht die Anfrage nie).
- Zusatzprobe, gleiche Erwartung: `POST /containers/archon-xyz-does-not-exist/restart` → heute `404`, soll `403`.
- Gegenprobe, damit nicht alles gesperrt ist: `GET /_ping` → `200`, `GET /containers/json` → `200`.

Der Test ist mutierend-frei, weil der Zielcontainer nicht existiert: Docker
antwortet mit 404, ohne etwas anzulegen oder zu starten. Er wurde am 2026-11-07
einmal ausgeführt, um den Ist-Zustand zu belegen (Ergebnis oben).

## 5. Anwendung (durch Michael, nicht durch diesen Auftrag)

Risiko: **mittel**. Bricht die Anwendung einen legitimen Pfad, dann genau diese:

1. **`backend/post_task_pipeline.py`** (paperclip-exec) — braucht `EXEC=1`.
   Steht heute auf `0`. Mit der Soll-Fassung ist exec dann wirklich zu: die
   Paperclip-Task-Ausführung schlägt mit 403 fehl. Entweder `EXEC=1` setzen
   (dann ist exec über den Proxy erreichbar — der heutige Ist-Zustand für die
   Erstellung) oder den Paperclip-Pfad auf `docker exec` über den Host umstellen.
2. **Restart/Stop über den Proxy** — braucht `ALLOW_RESTARTS=1` bzw.
   `ALLOW_STOP=1`. Nur nötig, wenn `DOCKER_HOST` auf den Proxy zeigt; heute
   nicht der Fall.
3. **Logs/Stats** — `CONTAINERS=1` bleibt nötig (ist gesetzt).

Schritte (nur wenn entschieden):

```
# 1. Rückweg sichern
docker exec docker-socket-proxy cat /tmp/haproxy.cfg > /root/haproxy.cfg.bak-$(date +%F)

# 2. Soll-Fassung einspielen (Datei ist bereits im Repo)
docker cp deploy/docker-socket-proxy/haproxy.cfg docker-socket-proxy:/tmp/haproxy.cfg

# 3. Regeln neu laden (kein Recreate, kein Container-Neustart)
docker exec docker-socket-proxy sh -c 'haproxy -c -f /tmp/haproxy.cfg && kill -HUP 1'
#    Falls das Image kein HUP-Reload beherrscht: docker restart docker-socket-proxy
#    (kurze Unterbrechung; ARCHON-OS ist nicht betroffen, es nutzt den Raw-Socket)

# 4. Negativtest + Gegenprobe aus Abschnitt 4
```

Rückweg: `docker cp /root/haproxy.cfg.bak-<datum> docker-socket-proxy:/tmp/haproxy.cfg`
+ `kill -HUP 1` (oder `docker restart docker-socket-proxy`). Der Proxy hat keinen
eigenen Zustand außer dieser Datei; ein Rollback ist damit vollständig.

## 6. Prüftiefe

- Gelesen: laufende `haproxy.cfg` (`docker exec … cat`, nur lesen), Env des Containers.
- Gemessen: die acht Aufrufe aus Abschnitt 1 (aus `ARCHON-OS` heraus, gegen den
  laufenden Proxy).
- Geprüft: `haproxy -c -f /dev/stdin` gegen die Soll-Fassung → Exit 0 (nur die
  Warnung „missing timeouts for backend docker-events", die die laufende Datei
  identisch erzeugt).
- Simuliert: 32 Allow-Regeln gegen 21 Pfade mit den heutigen Flags
  (`Regelwerk-Simulation, kein Live-Test`) → 0 Abweichungen.
- **Nicht** geprüft: das Verhalten des echten Proxys mit der neuen Datei. Das
  wäre die Anwendung, und die ist nicht Teil dieses Auftrags.

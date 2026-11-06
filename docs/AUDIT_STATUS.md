# Audit-Status — Archon OS

Stand: 2026-11-06 · Branch `refactor/critical-hardening`
Bezug: externes Code-Audit (God-File-Analyse, ~40 Punkte, A/B/P/S)

Dieses Dokument ist der Abarbeitungsstand. Jede Zeile nennt den **Messbefehl**,
damit der Status reproduzierbar ist und nicht aus dem Gedächtnis zitiert wird.

Legende: ✅ erledigt und belegt · 🟡 teilweise · 🔴 offen und gemessen · ⚪ ungeprüft

---

## Architektur

| # | Punkt | Status | Beleg / Messung |
|---|---|---|---|
| A1 | Monolith 16.254 Zeilen | 🟡 | `wc -l < main.py` → **11.321** (−30 %), weiterhin Monolith |
| A2 | Keine Modulstruktur | ✅ | `archon/core` (8), `archon/routers` (20), `backend/`, `utils/` |
| A3 | God Object | 🟡 | Routing + Kernlogik getrennt; Middleware/Lifespan/Config in `main.py` |
| A4 | Enge Kopplung | 🟡 | Orchestrierung + Router entkoppelt, `main.py` importiert weiter 50+ Module |
| A5 | 40+ Modul-Globals | 🔴 | `grep -cE "^[A-Z_][A-Z0-9_]* = " main.py` → **52** |
| A6 | Sync-I/O in async | 🟡 | `grep -c "asyncio.to_thread" main.py` → 15 |
| A7 | Kein DI / `Depends()` | 🔴 | `grep -c "Depends(" main.py` → **0** (DI erfolgt über `configure()`, nicht FastAPI-DI) |
| A8 | Config verstreut | 🔴 | unverändert, 15+ Dateien |

## Logikfehler

| # | Punkt | Status | Beleg / Messung |
|---|---|---|---|
| B1 | Race Condition MC-Lock | 🔴 | `threading.Lock` **und** `asyncio.Lock` parallel in `archon/core/mission_control.py:23,24` |
| B2 | Doppelte Proxy-Implementierungen | ✅ | `utils/reverse_proxy.py`, eine Klasse für alle Ziele |
| B3 | Docker-Socket ohne Schutz | 🟡 | `utils/docker_client.py` mit Allowlist; direkte Socket-Connects in `main.py` (920, 1021, 1032) bleiben |
| B4 | Path Traversal | ✅ | `utils/path_jail.py`, `safe_path` 12× in `main.py` |
| B5 | SQL-Injection | ⚪ | nicht geprüft |
| B6 | Stille Exceptions | ✅ | `except …: pass` = **0** projektweit; 2 nackte `except:` verbleiben |
| B7 | Cache-Invalidierung | 🟡 | TTL-Caches eingeführt, keine einheitliche Strategie |
| B8 | Blockierendes httpx in async | ⚪ | nicht geprüft |
| B9 | 50+ doppelte `api_route` | 🔴 | `grep -c "api_route(" main.py` → 50 |
| B10 | Hardcodierte Pfade | 🟡 | Audit nennt 300+; in `main.py`+`archon`+`backend`+`utils`: **169** × `/opt/data` |

## Security

| # | Punkt | Status | Beleg / Messung |
|---|---|---|---|
| S1 | Docker-Socket | 🟡 | siehe B3 |
| S2 | Path Traversal | ✅ | Path-Jail aktiv, 403 außerhalb der Wurzeln |
| S3 | Keys in Env/Logs | 🟡 | 117 Dateien auf 600, Maskierung im Live-Editor; kein Secret-Manager |
| S4 | Schwache Admin-Auth | ⚪ | in `main.py` keine Rollenprüfung mehr gefunden — verlagert, muss verifiziert werden |
| S5 | CORS mit `*` | ✅ | explizite Origin-Liste + LAN-Regex statt Wildcard |
| S6 | Sandbox-Escape | 🔴 | `api_run_python_sandbox` unverändert |
| S7 | YAML-Deserialisierung | ⚪ | `safe_load` verwendet, `!!python`-Tags nicht geprüft |
| S8 | Kein Rate-Limiting | 🔴 | kein `slowapi`/Middleware vorhanden; 200+ Endpunkte ungebremst |
| S9 | Telegram-Token im Klartext | 🟡 | Rechte gehärtet, Klartext in `.env` bleibt |
| S10 | **SSRF im Proxy** | ✅ | **siehe unten — behoben am 2026-11-06** |

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

Gemessener Bezugspunkt für P1–P8: `scripts/bench_routes.py`, 128 Routen, Median 73 ms warm.

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
# 22 Unit-Tests
.venv/bin/python -m pytest tests/test_egress_guard.py -q     # 22 passed
.venv/bin/python -m pytest tests/ -q                          # 167 passed, 4 skipped

# live, mit Service-Token
curl -H "X-Archon-Service-Token: $T" \
  "http://127.0.0.1:8501/api/proxy?url=http://169.254.169.254/latest/meta-data/"
# → 403 {"detail":"Metadaten-/Link-Local-Adresse 169.254.169.254 ist nie erlaubt"}

curl -H "X-Archon-Service-Token: $T" \
  "http://127.0.0.1:8501/api/proxy?url=http://10.0.0.5/admin"          # → 403
curl -H "X-Archon-Service-Token: $T" \
  "http://127.0.0.1:8501/api/proxy?url=http://127.0.0.1:8501/health"   # → 200
```

---

## Nächste Schritte (priorisiert)

1. **S8 Rate-Limiting** — 200+ Endpunkte ohne Bremse, darunter `/api/sandbox`
   und Container-Exec. Höchster verbleibender Hebel.
2. **B1 Race Condition MC-Lock** — der einzige Punkt, der Daten beschädigen kann
   statt nur zu stören: `threading.Lock` + `asyncio.Lock` parallel.
3. **S4/S7/B5/B8 verifizieren** — ungeprüft; erst messen, dann einordnen.
4. **S6 Sandbox-Escape**, **B3 Docker-Socket-Reste** in `main.py`.
5. **A5/A7/A8** — Globals, FastAPI-DI, Config-Schicht (großer Umbau).
6. **B10 Pfad-Config-Schicht** — 169 Stellen, eigener Tag mit eigener Baseline.

## Was nachweislich erledigt ist

A2, B2, B4, B6, S2, S5, **S10** — sieben Punkte, jeder mit Messbefehl oben.

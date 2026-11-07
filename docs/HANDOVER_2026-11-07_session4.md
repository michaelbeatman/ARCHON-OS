# Handover Session 4 — Archon OS

**Ersetzt** `docs/HANDOVER_2026-11-07_session3.md` als Sitzungsanker. Das **Fortschrittsblatt**
ist `docs/ROADMAP.md` — dort steht erledigt/offen/in Arbeit mit Messwerten. Dieses Dokument
enthält nur, was eine neue Session zum *Anfangen* braucht.

Stand: 2026-11-07, spät. Branch `refactor/a5-di-config`.
**Code-Stand: `f99e8c41`** — die Handover-/Roadmap-Commits danach sind reine Dokumentation.
`git log --oneline -1` liefert den jeweils aktuellen Kopf. Commits seit Fork-Punkt `de564278`:
`git rev-list --count de564278..HEAD` (beim Schreiben: 36). Working Tree: **0 geänderte Dateien**, 11 fremde
untracked Einträge (unangetastet, gehören Michael).

---

## 1. Copy-Paste für die nächste Session

```bash
cd /mnt/raid/AgenticOS-2026 && git log --oneline -1 && git status --short

# Tests — EXAKTER Aufruf, sonst Fehlalarme:
.venv/bin/python -m pytest tests/ -q          # Soll: 743 passed, 8 skipped (~28 s)

# Instanz
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/health   # 200
docker logs --since 10m ARCHON-OS 2>&1 | grep -c Traceback              # 0
```

**Der Testaufruf ist nicht beliebig:** `.venv/bin/pytest tests/` scheitert mit
`ModuleNotFoundError: No module named 'archon'` (Rootdir fehlt auf `sys.path`); ohne `tests/`
sammelt pytest `OpenMontage/` und `browser-use/` mit → 22 Collection-Errors. Wer die Zahl
nachprüft und den falschen Aufruf nimmt, jagt eine Regression, die es nicht gibt.

**`--reload` ist aktiv:** jede gespeicherte Datei ist sofort live. Während ein Agent
`main.py` schreibt, kann `/health` kurz `000` liefern — das ist ein Reload-Fenster, kein
Ausfall. Nachprüfen statt melden: dreimal `curl`, plus `docker ps` (Container `Up …`) und
`py_compile main.py`.

---

## 2. Was in dieser Session passiert ist (10 Commits)

| Commit | Wirkung |
|---|---|
| `1d170a92` | Compose-Entwurf entschieden: externe sprechende Volume-Namen, Digest-Pin, Host-Port 8645 (8644 hielt das native Gateway) |
| `cb90a157` | `hermes-net` als `external` — sonst bricht jeder Recreate an `hermes-webui` |
| `9229fba3` | Plan Avatar-Schreibpfad (Variante B) |
| `c7f19b55` | **Gate-Approve repariert**: Service-Extraktion statt `NameError`, Gate wird bei Fehlschlag nicht mehr verbraucht, Owner-Meldung ehrlich, 2 ungebundene Namen gebunden (+AST-Regressionsbremse) |
| `1c49ee09` | `docs/ROADMAP.md` als verbindliches Fortschrittsblatt |
| `6febf38e` | **R1**: `/api/roles` 2.608.401 B → 110.711 B, Rundlauf-Schutz (nur selbst materialisierte Pfade) |
| `9926a9ea` | Roadmap nachgezogen |
| `482300c6` | **Avatar-Variante B**: Schreibziel aus dem versionierten Baum raus, Legacy nur lesend, eigene Route; + Triage-Dokument |
| `0cf56ffc` | Roadmap nachgezogen |
| `f99e8c41` | **Drei Sicherheitsbefunde**: Upload-RCE, Vault-Jail auf Vault-Wurzel, voice-relay eingezäunt |

Zusätzlich ohne eigenen Commit: beide Hermes-Volumes migriert (Agent 414 Dateien/25.901.963 B,
Dashboard 3 Dateien/12.745 B, SHA256-identisch), Dashboard auf Digest-Pin neu errichtet,
Dashboard-Passwort als `password_hash`+`secret` in `~/.hermes/config.yaml` dauerhaft gemacht.

---

## 3. Verifizierte Kennzahlen (alle selbst gemessen)

- Tests **743 passed / 8 skipped**; Routen-Decorator **309** (unverändert über den Sicherheits-Commit).
- `main.py` wächst durch die Fixes (Gate-Service, Haertung) — Zeilenzahl vor dem Zitieren messen.
- Ungebundene Aufrufe in `main.py`: **0** (vorher 4, eigener AST-Lauf).
- `/api/roles`: **110.711 B** (vorher 2.608.401 B); nach GET→POST bleibt `roles.json`
  byte-identisch (SHA256-gleich), 10/10 data-URIs erhalten.
- Avatare: nach `GET /api/hermes/profiles` ist `git status -- short -- static/avatars` **0 Zeilen**
  (vorher 4 `M`) — Laufzeitdateien liegen in `~/.hermes/webui/static_avatars/` (5 Stück).
- Hermes-Stack: Dashboard `running`, `restarts=0`, Image `nousresearch/hermes-agent@sha256:e6d81ae5…`,
  Volume `archon-hermes-hermes-dashboard-data`; `hermes-agent` bleibt bewusst `Exited`.
- Sicherheitsproben live: anonym 401 auf `library/upload`, `voice-relay`, `DELETE /api/vault`;
  mit Service-Token auf `~/.hermes/config.yaml` → **403**, Datei unversehrt.

---

## 4. Offene Punkte (Reihenfolge aus `docs/ROADMAP.md` §3)

1. **`backend/hermes_updater.py:63`** roher `AF_UNIX`-Socket am Proxy vorbei (3–4 h).
2. **`_decision_followup`** (`main.py:3267-3269`) meldet „ausgeführt" ohne Body-Prüfung — derselbe
   Fehlertyp wie beim Gate, 30 min.
3. **Avatar-Upload-Route ohne Rollenzaun** (`hermes_profiles.py:99`, `POST …/avatar`) — schreibt Dateien,
   15 min + Test.
4. Tote UI-Pfade (166/1640 laut Handover, **nicht** nachgemessen).
5. Paket 3 (Struktur), `docs/PLAN_STRUKTUR_2026-11-07.md`.
6. Mikro-Performance (P1–P4 aus dem Audit, nie gemessen).
7. **Bei Michael:** Token-Rotation über BotFather; ausserdem Entscheidung zum hartkodierten
   RAG-API-Key `main.py:2287` (Klartext im Code, nicht geändert).

**Nicht mehr offen** (in dieser Session geschlossen): Gate-Approve, `/api/roles`-Payload,
Avatar-Schreibpfad, Upload-RCE, Vault-Reichweite, voice-relay.

---

## 5. Rollback

- Pro Commit `git revert <sha>`.
- **`main.py` und `archon/routers/_rbac.py` gehören zusammen** — Teil-Rollback lässt Router
  fail-closed sperren (503 auf geschützten Routen).
- Hermes-Compose immer mit `-p archon-hermes -f docker-compose.hermes.yml --env-file .env.archon`;
  ohne `--env-file` zeigt `OMNIROUTE_URL=http://localhost:20128/v1` im Container auf sich selbst.
- Alte Hash-Volumes (`1980851f…`, `f1e50a5f…`) sind absichtlich **noch da** (Sicherheitsnetz).

---

## 6. Was NICHT belegt ist (ehrlich)

- „Klasse A vollständig 123/123" ist **nicht reproduzierbar**: das Prüfskript lebt nur im Skill
  (`scripts/audit_route_guards.py`), nie in der Git-History. Eigener Lauf: 120 Routen mit Zaun,
  214 Schreib-Routen ohne, 9 mit Gefahrensignal → Triage hat daraus 0 offene Türen und
  1 kritischen Fall (library/upload, jetzt behoben) ergeben.
- `docs/AUDIT_STATUS.md` widerspricht sich: Kopf „12 ✅ · 21 🟡 · 3 🔴", 36 Tabellenzeilen aber
  **12 ✅ · 19 🟡 · 5 🔴**.
- Kein Viewer-Livetest, kein Lasttest, Promptfoo-Route nie live aufgerufen.
- Die Langfrist-Rotation des Telegram-Tokens ist Michaels Schritt, nicht erledigt.

---

## 7. Fallstricke, die diese Session gekostet hat

1. **`safe_path(extra_roots=[…])` erweitert nur** — es *ersetzt* die Default-Wurzeln nicht. Wer
   den Vault-Jail verengen will, braucht einen expliziten Containment-Check (so gelöst in
   `main.py:8494-8507`). Ohne ihn wäre der Fix wirkungslos gewesen.
2. **Compose-Netz:** `name:` ohne `external: true` heißt „mein Netz" → Recreate löscht es und
   scheitert an fremden Endpoints; der Zielcontainer ist dann schon gestoppt.
3. **Dashboard-Passwort:** Env schlägt Config-Hash; ohne registrierten Provider verweigert der
   Server bei `0.0.0.0` den Bind komplett.
4. **`| tail` verschluckt den Exit-Code** — eigene Messung war dadurch „EXIT=0" bei einem
   abgebrochenen Compose. Guards ohne Pipe fahren oder `set -o pipefail`.
5. **Testartefakte** dürfen nicht in `~/.hermes` landen: Fixtures konsequent auf `tmp_path`/Env.
6. **Avatar-Schreibziel** war der Grund für einen dauerhaft schmutzigen Working Tree — jetzt
   `ARCHON_AVATARS_DIR` → `/opt/data/webui/static_avatars` → `~/.hermes/webui/static_avatars`.

---

## 8. Erste Schritte einer neuen Session

1. `docs/ROADMAP.md` lesen (Fortschrittsblatt), dann dieses Dokument.
2. Copy-Paste-Block aus §1 fahren; Zahlen gegen §3 halten.
3. Offenen Punkt 1 (`hermes_updater`) oder 2/3 (kleine Fixes) aufnehmen — Michaels Wahl.
4. Nach jeder Etappe: **Roadmap** nachziehen, nicht ein neues Handover schreiben.

# Roadmap Archon OS — ein Blatt, gemessen

**Zweck:** Diese Datei ersetzt das Suchen in sieben Handover-Dokumenten. Sie führt an *einer*
Stelle: was erledigt ist (mit Commit und Beleg), was offen ist (mit Messwert), was gerade in
Arbeit ist, und was **nicht** belegt ist. Alles hier ist am 07.11.2026 abends gegen den
laufenden Stand gemessen; Zahlen ohne Messbefehl sind als „ungeprüft" markiert.

Stand: Branch `refactor/a5-di-config`; **Code-Stand `f99e8c41`** (danach nur Doku-Commits —
`git log --oneline -1` liefert den aktuellen Kopf, bewusst kein Sha hier).
Test-Soll: `.venv/bin/python -m pytest tests/ -q` → **743 passed / 8 skipped**, Working Tree sauber.

---

## 0. Selbstprüfung in 60 Sekunden

Wer wissen will, ob die Angaben hier stimmen, fährt genau das:

```bash
cd /mnt/raid/AgenticOS-2026
git log --oneline -6                      # die Commits dieser Session
git status --short                        # fremde Änderungen im Baum
.venv/bin/python -m pytest tests/ -q      # 685 bzw. 697 passed, 8 skipped
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/health          # 200
docker logs --since 10m ARCHON-OS 2>&1 | grep -c Traceback                     # 0
```

Der Testaufruf ist exakt so zu nehmen: `.venv/bin/pytest tests/` scheitert mit
`ModuleNotFoundError: archon`, und ohne `tests/` sammelt pytest `OpenMontage/` und
`browser-use/` mit (22 Collection-Errors). Nicht der Code ist dann kaputt, der Aufruf.

---

## 1. Erledigt in dieser Session (10 Commits, alle von mir gegengeprüft)

| Commit | Was | Beleg |
|---|---|---|
| `1d170a92` | Compose-Entwurf entschieden: externe sprechende Volume-Namen, Digest-Pin für beide Dienste, Host-Port 8645 statt 8644; falsche „1,8 GB"-Angabe korrigiert | `compose config` Exit 0; Ports `published: 8645`; Volumes `archon-hermes-hermes-*-data` |
| `cb90a157` | `hermes-net` als `external` — sonst bricht jeder Recreate an `hermes-webui` | Fehler wörtlich reproduziert, danach Recreate erfolgreich |
| `9229fba3` | Plan Avatar-Schreibpfad (Variante B: `/opt/data/webui/static_avatars`) | 256 Zeilen; 9 getrackte `custom_*`-PNGs, Ursache `profiles.py:46-48` |
| `c7f19b55` | Gate-Approve repariert (Service-Extraktion), Gate wird bei Fehlschlag nicht mehr verbraucht, Owner-Meldung ehrlich, 2 ungebundene Namen gebunden | 685/8 Tests; 4 ungebundene Aufrufe vorher → 0 nachher; 47 Assertions neu, 0 entfernt |
| `1c49ee09` | Diese Roadmap als verbindliches Fortschrittsblatt | 109 Zeilen, ersetzt das Suchen in 7 Handovern |
| `6febf38e` | **R1**: `/api/roles` 2.608.401 B → 110.711 B; Rundlauf-Schutz für die selbst materialisierten Avatare | eigener Rundlauf GET→POST→Datei: byte-identisch, Delta 0 %, 10/10 data-URIs erhalten, 108 bestehende Pfade unberührt; **711/8 Tests** |
| `9926a9ea` | Roadmap nachgezogen | — |
| `482300c6` | **Avatar-Variante B**: Schreibziel `/opt/data/webui/static_avatars` (Env `ARCHON_AVATARS_DIR` → Container → Home), Legacy-Baum nur noch lesend, eigene Route `main.py:10671`; Duplikate atomar | Live: nach `GET /api/hermes/profiles` ist `git status -- static/avatars` **0 Zeilen** (vorher 4 `M`); 5 Laufzeitdateien; Route 200/404, Traversal 404; **727/8 Tests** |
| `482300c6` | Triage der 9 Routen (`docs/TRIAGE_UNGUARDED_ROUTES.md`) | alle 9 hinter dem Auth-Gate (401 ohne Login selbst geprüft); 1 kritischer Einzelfund (library/upload) |
| `f99e8c41` | **Drei Sicherheitsbefunde geschlossen**: Upload-RCE (`basename`+`safe_path`+Zaun), Vault-Jail auf Vault-Wurzel begrenzt, `voice-relay` eingezäunt + `chat_id`-Validierung | Live: anon 401 auf allen drei; Token auf `~/.hermes/config.yaml` → **403**, Datei unversehrt; Routen 309 unverändert; **743/8 Tests**, 48 Assertions neu, 0 entfernt |

Zusätzlich erledigt, ohne eigenen Commit (weil Teil der obigen):
- **Volumes migriert und bit-verifiziert:** Agent 414 Dateien / 25.901.963 B, Dashboard 3 Dateien /
  12.745 B, beide SHA256-identisch, Rechte erhalten.
- **Dashboard-Passwort dauerhaft:** `password_hash` + `secret` in `~/.hermes/config.yaml`;
  Provider registriert sich ohne Env-Passwort, `/auth/password-login` liefert 401 bei falschem
  Passwort. Dashboard läuft nach Recreate auf dem Digest-Pin, `restarts=0`.

---

## 2. In Arbeit — drei delegierte Mandate (Stand: Ende Session 4, 07.11. abends)

Kein Punkt davon ist committet; die Läufe arbeiten im Working Tree und committen nicht selbst.
Zuerst die Berichte gegenmessen, dann pfadgenau committen.

| Mandat | Profil | Woran |
|---|---|---|
| 1 | `senior_fullstack_engineer` | `backend/hermes_updater.py:63` — roher `AF_UNIX`-Socket ablösen (Etappe 0 = nichts ändern ist erlaubt und muss begründet werden) |
| 2 | `devops_cloud_sec_specialist` | `archon/routers/hermes_profiles.py:100` — Rollenzaun für `POST …/avatar`, fail-closed, ohne Aussperrung der Durchlässigkeitspfade |
| 3 | `senior_fullstack_engineer` | `main.py:3335` Body-Prüfung in `_decision_followup` **und** `main.py:2287` RAG-Key → Env/fail-fast |

`482300c6` hat R1 und Avatar-B abgeschlossen — der alte Text dieses Abschnitts bleibt als
Fußnote: der Rundlauf-Schutz greift nur für Pfade, die `GET` aus dem gespeicherten data-URI
erzeugt hat; die 108 bestehenden `/static`-Pfade in `roles.json` bleiben Pfade.

---

## 3. Offen, priorisiert (aus Handover §7 plus Befunde dieser Session)

| Prio | Punkt | Messwert / Beleg | Aufwand |
|---|---|---|---|
| 1 | **`hermes_updater`-Socket am Proxy vorbei** — *in Arbeit (Mandat 1)* | `backend/hermes_updater.py:63` `AF_UNIX` | 3–4 h |
| 2 | **`_decision_followup` meldet „ausgeführt" ohne Body-Prüfung** (neu) — *in Arbeit (Mandat 3)* | `main.py:3335`, Aufrufer `main.py:3400` (Handover-Zahl 3267 war gedriftet) | 30 min |
| 3 | **Avatar-Upload-Route ohne Rollenzaun** (neu) — *in Arbeit (Mandat 2)* | `POST /api/hermes/profiles/{id}/avatar`, `archon/routers/hermes_profiles.py:100` — schreibt Dateien, kein Zaun, kein globales Middleware-Netz | 15 min + Test |
| 4 | **Tote UI-Pfade** | Handover: 166 von 1640 `getElementById`-Zielen ohne DOM-Element; von mir **nicht** nachgemessen | 2–4 h je Cluster |
| 5 | **Paket 3 (Struktur)** | `docs/PLAN_STRUKTUR_2026-11-07.md`, 5 Etappen, nicht gestartet | 1–2 Wochen |
| 6 | **Mikro-Performance** (DB 1,25 ms, N+1 max 8 Queries, 411 `fetch`) | aus Grundprüfung, nicht neu gemessen | niedrig |
| — | **RAG-API-Key `main.py:2287`** — **entschieden**: Env/Secret-Store, fail-fast; in Mandat 3 | Klartext im Code, `--api-key`-Argument | 15 min |

---

## 4. Was ich **nicht** belegen kann — bitte nicht als erledigt lesen

- **„Klasse A vollständig, 123/123, Differenz 0"** (`1424e3dc`) ist aus dem Repo heraus
  **nicht reproduzierbar**: das Prüfskript existiert nur als Skill-Skript, nie in der
  Git-History. Mein Lauf gegen den heutigen Stand ergibt **120 Routen mit Zaun** und 9
  Kandidaten mit Gefahrensignal (siehe §3.1).
- **`docs/AUDIT_STATUS.md` widerspricht sich selbst:** der Kopf sagt „12 ✅ · 21 🟡 · 3 🔴",
  die 36 Tabellenzeilen zählen aber **12 ✅ · 19 🟡 · 5 🔴**. Der Kopf ist veraltet; welche
  Zeile im Einzelfall stimmt, ist ohne Einzelprüfung offen.
- **Viewer-Livetest, Promptfoo-Route live, Lastmessung:** weiterhin nicht gemacht (aus Handover §9).
- **Kaltstart des Dashboards:** inzwischen gemessen (~15 s bis `HERMES_DASHBOARD_READY`,
  `restarts=0`) — das ist der einzige der vier Punkte, der jetzt belegt ist.
- **Mock-Dispatcher/Browser-Verhalten:** nichts davon habe ich selbst gefahren; Aussagen dazu
  stammen aus Profilberichten.

---

## 5. Wie es weitergeht (Vorschlag)

1. **Jetzt:** `POST /api/v1/library/upload` absichern (§3.1) — authentifizierte RCE, kleinster
   Aufwand mit größter Wirkung: `basename` + `safe_path` + Rollenzaun.
2. **Danach:** `DELETE /api/vault` auf die Vault-Wurzel begrenzen (§3.2) und `voice-relay`
   einzäunen (§3.3).
3. **Erst dann** die großen Blöcke: 48 Proxy-Routen (§3.4), Paket 3 (§3.8).
4. **Nicht mehr geführt:** die Telegram-Token-Rotation — Michael erledigt sie selbst außerhalb
   dieses Repos (Stand 07.11. gestrichen).

Nach jeder Etappe wird **diese Datei** nachgezogen (Status + Messwert), nicht ein neues
Handover geschrieben. Handover bleiben für den Sitzungsübergang; diese Datei ist der Fortschritt.

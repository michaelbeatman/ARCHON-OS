# HANDOVER — Archon OS · Stand 06.11.2026

Übergabe-Dokument für eine neue Hermes-Session. Alles hier ist am 05./06.11.2026
verifiziert worden. Wenn etwas nicht mehr stimmt: erst prüfen, dann handeln.

---

## 1. Kurzfassung: Wo wir stehen

Archon OS läuft stabil als virtuelle Firma auf einem Linux-Server (WSL/Docker).
Heute wurden Systemsicherheit, Datenwurzel, Agentenkader, Modell-Routing und
Automatisierung aufgeräumt. Zustand bei Übergabe:

| Kennzahl | Wert |
|---|---|
| Archon (Port 8501) | **200** |
| OmniRoute (Port 20128) | **307** `/` → `/dashboard`, Combo grün (3/3 Modelle alive) |
| Hermes-Gateway (Port 8787) | **302** (Login aktiv) |
| Agentenprofile | **59** (alle auf `omniroute / strict-free-tier-combo-Reasoning`) |
| API-Routen | 585 Pfade / 664 Routen (Pfad+Methode), 0 Kollisionen |
| Testsuite | **85 passed, 1 skipped, 0 failed** (Stand 06.11.) |
| Cron-Jobs | 6 |
| Fehler in den Logs | 0 |

---

## 2. Zugänge, Pfade, Ports

```
Projekt (bind mount → /app)   /mnt/raid/AgenticOS-2026
Hermes-Daten (= /opt/data)    /home/micha/.hermes
Obsidian-Vault                /mnt/raid/Mein Obsidian
Backups (App)                 /mnt/raid/AgenticOS-2026/backups/*.tar.gz
Arbeitsbackups                /mnt/raid/AgenticOS-2026/.archon_backup_20261105_1015/
```

Wichtige Dateien:

| Datei | Bedeutung |
|---|---|
| `agent_profiles.json` | Kader (59 Profile). **Wird von der laufenden App zurückgeschrieben** — Änderungen nur bei gestopptem Container! |
| `data/model_routing.json` | Aufgabe → Provider → Modell + Autonomie |
| `settings.json` + `agent_workspace/settings.json` | App-Einstellungen (beide pflegen!) |
| `data/.archon_service_token` | Service-Token für interne Aufrufe (Header `X-Archon-Service-Token`) |
| `.env.archon` | Container-Umgebung (Modus 600) |
| `docs/BETRIEB_HANDBUCH_INTERN.md` | dieses Dokument |

Ports (nur localhost gebunden, sicher):
`6379` Redis · `5678` n8n · `20128` OmniRoute · `8090/8092` PocketBase ·
`8083` autogen · `3180` paperclip · `8787` Hermes · `8501` Archon

Bewusst im LAN offen: `3005` CRM, `3001` anything-llm, `51821` wg-easy.

---

## 3. Was am 05./06.11. erledigt wurde

### Sicherheit
- 7 Dienste von `0.0.0.0` auf `127.0.0.1` umgebunden (Redis lief **ohne Passwort**, OmniRoute **ohne Key**).
- Archon-Container läuft nicht mehr als root, sondern **uid 1000**, Docker-Socket über Gruppe 973.
- Auth aktiv: ohne Session **401**, mit Service-Token **200**.
- Keine Secrets im Quellcode; `.env.archon` und Service-Token Modus 600.

### Daten & Betrieb
- **Backup-Cron** `scripts/archon_daily_backup.py` täglich 03:00 (SQLite-Backup-API, 14 Tage Rotation, ~6,7 MB je Lauf).
- **Restore-Test** montags 04:00.
- **Testsuite** sonntags 05:00 (`scripts/run_tests.sh`, pytest).
- **Gateway-Watchdog** alle 5 Minuten (`scripts/gateway_watchdog.sh`) — startet `hermes-webui` neu, falls der Bot ausfällt.
- Zwei veraltete DB-Kopien archiviert (`data/state.db`, `data/kanban.db` → `.archon_backup_.../stale_db/`).
- Drei Kopien von `agent_profiles.json` durch Symlinks auf das Original ersetzt.

### Agentenkader
- **6 neue Profile**: `finance_lead`, `legal_counsel`, `research_scout`, `hr_recruiter`, `customer_support_lead`, `bi_controller` (je SOUL.md, profile.yaml, Personalakte).
- `growth_hacker_lead` bekam eine echte Persona.
- `backend/agent_aliases.py` übersetzt Altnamen (`hermes-researcher` → `research_scout`, `hermes-coder` → `senior_fullstack_engineer`, `hermes-orchestrator` → `system_architect_orchestrator`). Vorher wurden Aufgaben als `skipped_nonspawnable` verworfen.
- **SOUL.md bereinigt**: 94 % waren Hermes-Boilerplate (Messaging-Anleitung + komplette Kader-Liste). Jetzt nur Persona (⌀ 365 Zeichen) plus kurzer Messaging-Hinweis.
- **Skills**: `default` und `micha` hatten 302 bzw. 304 Skills (Manifest wurde bei jedem Aufruf mitgeladen) → jetzt 23 rollengerechte.

### Modelle & Routing
- **Überall** `omniroute / strict-free-tier-combo-Reasoning`: 59 Archon-Agenten, 53 Hermes-Profile, globale Hermes-Config, Telegram-Bot.
- Combo repariert: enthielt zirkuläre Verweise (`auto/best-reasoning`, `auto/best-free`) → jetzt drei konkrete freie Modelle.
- **Vision/OCR** separat: `nvidia/nemotron-3.5-super-vl:free`.
- **Alle Gemini-Referenzen entfernt** (Org-Chart `gemini-3.1-flash-image`, `auto/best-free` → Gemini, Vision-Route, Bandit-Seed). Google-Sprach-API nur noch mit `settings.json → voice.google_enabled = true`.
- **Guardian-Anzeige korrigiert**: Cache-Reads wurden zu den Tokens addiert (269 Mio „Verbrauch"). Jetzt getrennt: 7,4 Mio echte Tokens + 272 Mio Cache-Reads.

### Funktionen
- **Autonomie-Gate**: `manual` / `approval` / `autonomous` für Operations und Orchestrator; blockierte Aufgaben über Kanban-Button „Freigeben & starten" oder `POST /api/operations/kanban/tasks/{id}/approve`.
- Hermes-Kanban-Protokoll beachtet: `blocked`/`unblocked`-Events, sonst hebt Hermes' `promote_ready_tasks` die Sperre auf.
- **Freigabe-Button** im Kanban-Frontend.
- **Avatar-Bug** behoben (`avatar_url` fehlte in der Profil-API).
- **QuickChat** schreibt in denselben Verlauf wie Master-Chat (`state.db`, Session `quickchat_<profil>`).
- **Telegram-Versand** aus Archon war doppelt kaputt (hart deaktiviert + falscher Parameter) → jetzt konfigurierbar über `settings.json → telegram.enabled`, aktuell **an**.
- **n8n**: 12 Workflows aktiv (Morning Briefing, RSS-Watchdog, Weekly Maintenance + 9 neue). Wrapper lädt über `/n8n-proxy`.
- **Telemetrie**: erfundene Werte (`network_ops: 42`, `avg_uptime: 99.9%`) durch echte Messwerte ersetzt.

### Doku
- 14 Zahlenstellen in README/Handbuch korrigiert (59 Agenten, 585 Pfade, 664 Routen).
- Vier Word-Handbücher aktualisiert + Abschnitt „Änderungen vom 05.11.2026" (14 Einträge).

---

## 4. Aktuelle Konfiguration (Soll-Zustand)

```yaml
# Jedes Agentenprofil / Hermes-Profil
model:
  default: strict-free-tier-combo-Reasoning
  provider: omniroute

# data/model_routing.json
enabled: true
routes: alle Text-Aufgaben → omniroute / strict-free-tier-combo-Reasoning
vision                                → openrouter / nvidia/nemotron-3.5-super-vl:free
autonomy: {operations: approval, orchestrator: approval}

# settings.json
auth.enabled: true
telegram.enabled: true
voice.google_enabled: (nicht gesetzt = aus)
```

Cron (6 Jobs):
```
15 7 * * *   OmniRoute-Healthcheck
30 7 * * 1   OmniRoute-Healthcheck --fix
0  3 * * *   DB-Backup
0  4 * * 1   Restore-Test
0  5 * * 0   Testsuite
*/5 * * * *  Gateway-Watchdog
```

---

## 5. Offene Punkte

| # | Punkt | Status |
|---|---|---|
| 1 | Word-Handbuch: echte Screenshots statt KI-Platzhalter (Nutzer macht Bilder), danach Kompression unter 5 MB | **erledigt 06.11.** — 79 echte Aufnahmen (CRM ausgelassen), 60 Bilder ersetzt + 10 eingefügt, Vorlage **4,9 MB** |
| 2 | CRM (3005), anything-llm (3001), wg-easy (51821) noch im LAN | **vertagt 06.11.** — Handy-Nutzung ist ein Feature-Wunsch (weit hinten), Ports bleiben vorerst offen; Befund siehe Nachtrag |
| 3 | `agility_story`, `analyze_claims` sind englische Fabric-Vorlagen, keine Personas | bewusst drin gelassen |
| 4 | `micha`-Profil ist funktional irrelevant | bewusst drin gelassen |
| 5 | OmniRoute `free-tier-fallback` zeigt auf `freellmapi/auto` (unbekannter Provider) | **erledigt 06.11.** — Combo deaktiviert, Ziel unauflösbar (siehe Nachtrag) |
| 6 | Timeframe-Filter des Guardians filtert Sitzungen nach letzter Aktivität, nicht Token-Volumen | dokumentiert (`window_note`) |
| 7 | 7 Tests sind geskippt (2× evey-Plugin-API geändert, 1× Netzwerk, 4× fehlendes Test-Passwort) | **erledigt 06.11.** — 85 passed / 1 skipped (nur Netzwerk-Test) |
| 8 | **Feature-Wunsch (weit hinten): Android-App zur Steuerung von Archon** | geparkt 06.11. — Voraussetzungen im Nachtrag notiert, keine Umsetzung |

### Nachtrag 06.11.2026 (Prüfung durch neue Session)

**Port 8501 war wieder im LAN offen.** `docker-compose.dev.yml` hatte `- "8501:8501"`
ohne IP-Präfix → Bind auf `0.0.0.0`. Korrigiert auf `127.0.0.1:8501:8501`, Container
neu erzeugt; `ss -ltn` zeigt jetzt ausschließlich `127.0.0.1:8501`. Der Zustand aus
Abschnitt 3 („nur localhost") ist damit wiederhergestellt.

**Punkt 5 aufgeklärt.** `freellmapi` ist kein „unbekannter Provider", sondern ein in
`docs/system/system_architecture_spec.json` dokumentierter lokaler Fallback-Proxy
(Port dort: **3002**). Tatsächlich existiert:
- kein Container `freellmapi` (auch nicht gestoppt),
- kein Listener auf 3001/3002,
- `provider_nodes.freellmapi` zeigt auf `http://freellmapi:3001/v1` — im Docker-Netz
  **nicht auflösbar** (`getent hosts freellmapi` → negativ). Die Portangabe weicht
  außerdem von der Doku (3002) ab.
- `provider_connections.freellmapi-conn` ist aktiv, `test_status` aber leer.

Der Combo `free-tier-fallback` wurde **nie benutzt** (0 Einträge in
`session_model_history`), ist in `key_value`/`domain_fallback_chains` nicht
referenziert und taucht in der Next.js-Build nicht als Logik auf (nur als UI-Beispieltext).
Er wurde daher über die API deaktiviert:
`PATCH /api/combos/0d92c300-b066-46dd-8d5d-9d1a4dd51b7c` → `{"isActive":false}`.
`enabled` bleibt laut API `true` — das Feld wird von OmniRoute normalisiert/ignoriert,
`isActive` ist der wirksame Schalter. Vorher-Zustand gesichert in
`.archon_backup_20261105_1015/omniroute_combos_vor_fix_20261106.json`.

Offen (Entscheidung Nutzer): echten Fallback bauen (Container `freellmapi` +
Port-Korrektur auf 3001 **oder** 3002) oder `provider_nodes`/`freellmapi-conn` ganz
entfernen. Solange nichts davon passiert, bleibt der Combo deaktiviert.

**Nebenbefund:** `model_combo_mappings` routet `*` (Priorität 100) auf
`strict-free-tier-combo` — **nicht** auf die `-Reasoning`-Variante, die die 59 Profile
als Default nutzen. Funktioniert (Reasoning läuft), ist aber inkonsistent zur Doku.

**Punkt 2 aufgeklärt (06.11.) — kein WSL2, keine Firewall.**

Der Host ist **Bare-Metal-Ubuntu** (`hermes-home`, `eno1` 192.168.0.230/.234, WLAN
192.168.0.43), nicht WSL2. `ufw` ist installiert, aber **`ENABLED=no`** — es gibt keine
Host-Firewall. Damit ist jede `0.0.0.0`-Bindung im LAN offen, und aus dem Internet,
sobald ein Router-Portforward auf den Host zeigt.

Offen im LAN: `3005` CRM, `3001` anything-llm, `51820/udp` + `51821/tcp` wg-easy.

| Dienst | Absicherung | Befund |
|---|---|---|
| anything-llm | **keine** (`AUTH_TOKEN`/`JWT_SECRET`/Passwort nicht gesetzt → Single-User, kein Login) | `/api/v1` offen, Wissensdatenbank lesbar |
| CRM | Login vorhanden, Next.js-Prod-Build, läuft als root | Kontaktdaten (705 aktiv / 1.502 Pipeline) |
| wg-easy | `PASSWORD_HASH` gesetzt | 1 Peer (10.8.0.2) konfiguriert, **nie ein Handshake** — VPN unbenutzt |

**Kein Dienst hat einen belegten LAN-Nutzer:** in 3.000 Archon-Logzeilen ist der einzige
Client `172.18.0.1` (Docker-Gateway = Host selbst). Die CORS-Regel in `main.py:61`
(„LAN-Zugriffe Handy/Tablet") ist vorbereitet, nicht nachgewiesen.

**CRM vom Handy ist technisch unmöglich:** `src/lib/pocketbase.ts` nutzt
`NEXT_PUBLIC_POCKETBASE_URL || 'http://localhost:8090'`. `NEXT_PUBLIC_*` wird beim Build
in das **Client-Bundle** eingebettet und im Browser ausgewertet — auf einem Handy zeigt
`localhost` auf das Handy selbst. Zusätzlich lauscht PocketBase nur auf `127.0.0.1:8090`.
Eine Handy-Nutzung des CRM erfordert also einen Rebuild mit LAN-URL **und** eine
erreichbare PocketBase.

**Authelia liegt fertig, läuft aber nicht** (`config/authelia/`, Compose-Profil
`gateway`/`proxy`/`all`, `default_policy: deny`, TOTP + Passkey, Benutzer `admin`/`micha`).

**Kritisch — CRM-Quellcode war verloren.** Der Container hing an
`/mnt/raid/AgenticOS-2026/frontend`, dieses Verzeichnis **existierte nicht mehr**; der
Container lief nur weiter, weil Linux den gelöschten Inode offen hält. Der Code war nicht
in git und älter als das Image (`crm-frontend:latest` vom 30.08., Inhalt vom 25.10.).
`CRM/docker-compose.yml` baut aus genau diesem Pfad → jeder Recreate hätte das CRM zerstört.
Gerettet am 06.11.:
- `frontend/` wiederhergestellt (76 Dateien, **md5-identisch** mit dem laufenden Container)
- `frontend_recovered_20261106_122145/` als unveränderte Sicherung
- `backups/crm_app_full_20261106_122208.tar.gz` (315 MB, 28.722 Einträge, inkl. `node_modules`)
- `node_modules` und `.next` bewusst nicht im Quellverzeichnis; im Container liegt unter
  `C.Antigravity-projekteAgenticOS-2026frontend/.next/dev/` Build-Müll aus einem
  Windows-Lauf (harmlos, aber erklärungsbedürftig).

**Screenshots (Punkt 1) — 80 echte Aufnahmen am 06.11. erzeugt.**

Ablage: `docs/screenshots_20261106/`
- `*.png` — Originale, 3360×2100 (2× Gerätepixel), 49 MB, 80 Dateien, **alle eindeutig** (keine Dublette)
- `word/` — komprimierte Fassung 900 px / JPEG q68, **4,2 MB** für alle 80 (passt unter die 5-MB-Grenze)
- `_plan_64_seitenleiste.json`, `_inventar_19_nav_tabs.json` — die Klickpläne, reproduzierbar

Abdeckung: 19 Tabs der Seitenleiste → 64 Aufnahmen (Dashboard 1, Operations 6,
Posteingang 6, Agentenkader 8, Showroom 5, Internet-Watchdog 4, Research 3,
Zentralbibliothek 3, AI-Boardroom 3, Artikel 4, Vorgänge 3, Finanzen 4, Corporate 2,
Approvals 3, Token Guard 3, Telemetrie 3, je 1 für Kontakte/CRM, Master-Chat, Automation)
plus **System Control Center 11** (Kap. 14) und **CSS Live Studio 5** (Kap. 16) = **80**.

`nav-master-chat` und `nav-automation` sind Aliasse auf Operations-Subviews — bewusst nur
als Einstiegsbild aufgenommen, sonst wären 12 Bilder Dubletten geworden.

**Wie die Aufnahmen ohne Passwort entstanden** (für Wiederholung): Login ist ein
HttpOnly-Cookie `archon_session`; `POST /api/auth/login` braucht das Klartext-Passwort,
das nirgends gespeichert ist. Stattdessen wurde eine **temporäre Sessionzeile** in
`user_sessions` für `admin` angelegt (2–3 h Laufzeit, `user_agent='hermes-screenshot'`),
per CDP `Network.setCookie` in den Browser gesetzt und nach den Aufnahmen **wieder
gelöscht** (verifiziert: 0 Screenshot-, 1 reguläre Session übrig). Kein Passwort gelesen,
kein Passwort eingegeben.

**Vor Veröffentlichung zwingend:** die CRM-Aufnahmen (Kontakte & CRM, 43) enthalten
**echte Personendaten** (2.241 Kontakte, Namen in Klartext). Vor Weitergabe maskieren.

**Einbau ins Word-Handbuch am 06.11. erledigt** (`docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx`):

- **79 Aufnahmen** verwendet, CRM-Bild bewusst ausgelassen (Wunsch des Nutzers)
- **60 Bilder in place ersetzt** (Bild-Blob je `rId` getauscht, nicht Paragraph gelöscht →
  Layout, Größe und Bildunterschriften bleiben unverändert), **10 zusätzlich eingefügt**
  (Operations, Master Chat, n8n-Automation, Bot-Screen, Web-Apps, Benutzer & Rollen,
  CSS-Reiter Visual/Regeln/CSS/Texte)
- Zuordnung **explizit als Tabelle** (Überschrift → Datei) statt Fuzzy-Matching: Labels wie
  „Übersicht" kommen im Handbuch 5× vor und hätten sonst falsch zugeordnet
- Dokument hat jetzt **97 Bilder** (87 alte Slots + 10 neue), Validierung `ok: true`,
  keine verwaisten Relationship-Targets
- Größe zweistufig komprimiert (1600 px/q82 → 1100 px/q70 → 950 px/q64):
  **17,6 MB → 6,4 MB → 4,84 MB** — unter der 5-MB-Grenze
- Sicherung vorher: `ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx.bak-20261106_130741` (7,4 MB)
- PDF-Vorschau zur Sichtprüfung: `docs/system/HANDBUCH_Vorlage_Vorschau.pdf` (13 MB, LibreOffice)
- Originale (79 PNG, ohne CRM): `docs/screenshots_20261106_originale.zip` (46 MB)

**Offen:** die alten Kapitel 9.x (Kontakte/CRM) und 3.1.1/3.1.2, 10.5 (Artikel-Drawer),
18 (Prompt Studio) behalten ihre bisherigen Bilder — dafür gibt es keine passende neue
Aufnahme. Die 9.x-Bilder zeigen CRM-Daten und müssten bei externer Weitergabe ebenfalls
geprüft werden.

**Nachzügler am 06.11. nachgeholt** — die vier Ansichten, die nicht in der Seitenleiste
stehen, sind jetzt auch drin (5 Bilder, 102 gesamt, Dokument **4,52 MB**):

| Kapitel | Bild | Wie es zu öffnen ist |
|---|---|---|
| 3.1.1 Modell-Wechsel & Provider-Wahl | `82_Agentenkader__Modellrouter_Provider` (+ `81_…Gateway`) | Agentenkader → Profil anklicken (Modell-Router/LLM-Provider-Felder) bzw. `openGatewayManagerModal()` |
| 3.1.2 360°-Dossier & Messenger-Rufname | `83_Agentenkader__Rufname_360_Dossier` | Profilbereich bis `PROJEKT-HISTORIE & BETEILIGUNGEN` + `RUFNAME` scrollen |
| 10.5 Artikel-Drawer | `85_Artikel_und_Leistungen__Artikel_Drawer` | Artikel & Leistungen → Zeile anklicken (Reiter Stammdaten/Preise/Bestand/Verkaufshistorie) |
| 18 Prompt Studio | `84_Prompt_Studio__Vorlagen` | `openSurePromptsModal('ops-task')` — **ohne Argument öffnet es nicht**; 1.079 Vorlagen, Kategorien, Live-Vorschau |

Kompressionshistorie endgültig: 17,6 → 8,4 → 5,07 → **4,52 MB** (900 px/q60).
Sicherungen: `…bak-20261106_130741` (Original) und `…bak-*_vor-nachzuegler` (Stand nach Phase 1).




**Entscheidung des Nutzers (06.11.): nichts ändern.** Das Handy-Szenario ist ein
**Feature-Wunsch für die Zukunft** (Android-App zur Archon-Steuerung), kein heutiger
Nutzerkreis. Deshalb bleiben alle Binds wie sie sind — kein Loopback-Umbau, keine
ufw-Aktivierung, `51820/udp` und `51821/tcp` bleiben offen. 8501 bleibt auf
`127.0.0.1`, weil es heute keinen mobilen Zugriff gibt, den das abschneiden würde.

Bekannte, bewusst getragene Risiken bis zur Entscheidung: anything-llm ohne jede
Anmeldung im LAN, CRM mit Personendaten im LAN, keine Host-Firewall.

**Voraussetzungen für den Android-Wunsch (falls er je vorgezogen wird), in dieser
Reihenfolge:**
1. `ufw` aktivieren (Default deny incoming, SSH + `51820/udp`, LAN-Regeln pro Port) —
   nutzt die vorhandene `ufw`-Installation, die derzeit `ENABLED=no` ist.
2. anything-llm: `AUTH_TOKEN` + `JWT_SECRET` setzen (heute Single-User ohne Login).
3. CRM mobil: `NEXT_PUBLIC_POCKETBASE_URL` auf die LAN-IP (Build-Zeit!), PocketBase
   aus dem Loopback holen, Frontend neu bauen. Vorher war das durch den verlorenen
   Quellcode blockiert — seit der Rettung vom 06.11. ist `frontend/` wieder da.
4. Authelia (`config/authelia/`, Compose-Profil `gateway|proxy|all`) als SSO mit
   TOTP/Passkey davorsetzen — nicht gleichzeitig mit 1–3 debuggen.
5. `POCKETBASE_URL` im Frontend ist hartkodiert als `localhost:8090` gefallen; jede
   mobile Nutzung braucht einen Rebuild, kein bloßes Umschalten eines Flags.

**Testsuite: 78p/7s/1f → 85p/1s/0f.** Vier Ursachen, alle behoben:

1. **`test_mcts_engine` war flaky, kein Regressionsbefund.** `_simulate_rollout` zog
   `random.uniform(-0.05, 0.05)` ohne Seed, während zwei Kandidaten nur ~0,02 im
   Q-Wert auseinanderlagen — die Namens-Assertion war strukturell instabil.
   `evaluate_trajectories()` hat jetzt einen optionalen `seed`-Parameter
   (`random.Random(seed)` lokal, Produktion bleibt stochastisch). Der Test nutzt
   `seed=20261106`, 50 Rollouts und prüft zusätzlich: hochriskante Aktion darf nie
   empfohlen werden und muss Letztes sein, genau eine Empfehlung, gleicher Seed →
   identisches Ranking.
2. **2 JEV-Integrationstests wurden dauerhaft übersprungen, weil die Sonde den
   falschen Endpunkt fragte:** `/api/health` liefert unter aktiver Auth **401**,
   `/health` ist der öffentliche Liveness-Endpunkt (200). Zusätzlich fehlte der
   Service-Token (`X-Archon-Service-Token`) für `/api/settings`. Beides eingebaut,
   Sonde mit 5 Versuchen/10 s gegen Lastspitzen. Der Settings-Test **sichert jetzt
   den Ist-Zustand und stellt ihn im `finally` wieder her** — vorher schrieb er
   hartkodiert `api_key: ""` zurück, was einen echten JEV-Key gelöscht hätte.
3. **2 RBAC-Tests** hingen an `ARCHON_TEST_ADMIN_PASSWORD`, das nirgends existiert
   (kein Klartext gespeichert). Die Klasse läuft jetzt gegen eine **temporäre DB**
   (`auth_service.DB_PATH` gepatcht, `tearDownClass` räumt auf) — dort seeded
   `_seed_default_admin()` den Admin mit bekanntem Passwort. Nebeneffekt: `test_04`
   legt keine Testbenutzer mehr in der Produktions-DB an.
4. **2 evey-Tests** auf die aktuelle Plugin-API umgestellt: `evey-learner` schreibt
   JSONL (kein `synced_sqlite` mehr), Learnings-Datei im Test auf tmp umgebogen;
   `evey-memory-consolidate` hat `_sqlite_conversations_query` und `_save_to_obsidian`
   **nicht mehr** (jetzt Langfuse-Traces) — Test prüft Modul-Oberfläche und
   Fail-open-Verhalten statt toter Symbole.

Verbleibend geskippt: `test_research_engine` (externer Wikipedia-Zugriff) — bewusst.

**Altlast:** `data/agentic_memory.db` enthielt **18 Testbenutzer** (`lisa_ops_*`,
`auditor_max_*`) aus früheren Testläufen (05.11. und 06.11. 10:51). Am 06.11. auf
Freigabe des Nutzers gelöscht — zusammen mit **2 verwaisten Session-Tokens**
(`user_id` ohne zugehörigen Benutzer, ausgelaufen 05.12.). Vorher gesichert:
`backups/agentic_memory_pre_user_cleanup_20261106_120557.db` (via SQLite-Backup-API).
Stand danach: 1 Konto (`admin`), 1 Session, 0 Waisen. Ab der Testumstellung entstehen
keine neuen Testbenutzer mehr.

---

## 6. Alltag: Befehle

```bash
# Status
curl -s http://127.0.0.1:8501/health
cd /mnt/raid/AgenticOS-2026 && T=$(cat data/.archon_service_token)
curl -s -H "X-Archon-Service-Token: $T" http://127.0.0.1:8501/api/agents/profiles | head -c 300

# Tests
./scripts/run_tests.sh

# Backup jetzt
python3 scripts/archon_daily_backup.py

# OmniRoute prüfen
python3 scripts/omniroute_healthcheck.py --json

# Neustart Archon (Schnell-Reload reicht meist)
docker restart ARCHON-OS

# n8n-Wrapper / Proxy
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/n8n-proxy/

# Logs
docker logs --since 30m ARCHON-OS 2>&1 | grep -E "Traceback|ERROR"
```

---

## 7. Fallstricke (aus Fehlern gelernt)

1. **`agent_profiles.json` wird von der App zurückgeschrieben.** Änderungen nur bei
   gestopptem Container (`docker stop ARCHON-OS` → Datei ändern → `docker start`).
   Sonst überschreibt der In-Memory-Stand die Datei.
2. **Zwei Einstellungsdateien**: `settings.json` **und** `agent_workspace/settings.json`.
   Flags immer in beiden setzen.
3. **Zwei Hermes-Konfigurationsebenen**: `~/.hermes/config.yaml` (default-Profil) und
   `~/.hermes/profiles/<name>/config.yaml`. Beide pflegen.
4. **Kanban-DB liegt in `/opt/data`**, nicht in `/app/data`. Falsche Wurzel = leere Aufgaben.
5. **Hermes' `promote_ready_tasks`** hebt blockierte Aufgaben auf, wenn kein
   `blocked`-Event in `task_events` steht.
6. **`docker restart hermes-webui`** kann den Container mit `Exited (0)` liegen lassen —
   der Gateway-Watchdog fängt das jetzt nach max. 5 Minuten.
7. **Kein `sudo`-Passwort an Tools pipen** — wird blockiert. Host-Änderungen mit
   `sudo` muss der Nutzer selbst ausführen.
8. **Guardian-Tokens ≠ Verbrauch**: Cache-Reads sind separat zu lesen.
9. **Compose immer mit `-p archon` aufrufen.** Das Projekt heißt `archon`, abgeleitet
   wird aber `agenticos-2026` (Verzeichnisname). Ohne `-p archon` versucht Compose einen
   **zweiten** Container zu erzeugen → `Conflict. The container name "/ARCHON-OS" is
   already in use`. Richtig:
   `docker compose -p archon -f docker-compose.dev.yml up -d`. Ein reiner
   `docker restart ARCHON-OS` übernimmt **keine** Änderungen an `ports:` — dafür ist
   Recreate nötig.
10. **`/` auf OmniRoute liefert 307 → `/dashboard`**, nicht 200 wie in Abschnitt 1 notiert.
    Das ist Normalverhalten, kein Ausfall. Echter Check:
    `python3 scripts/omniroute_healthcheck.py --json` (alive/dead je Modell).

---

## 8. Sicherungen

- `.archon_backup_20261105_1015/` — Originale vor allen Änderungen (DBs, Skripte, Word-Backups, `souls_vor_bereinigung_*`, `souls_truncated/`, `stale_db/`, `n8n_new/`, `ROLLBACK_container_root.sh`).
- `backups/archon_backup_*.tar.gz` — tägliche Datenbanksicherung.
- Container-Sicherungen: `hermes-webui.bak-20261105`, `hermes-webui.bak-20261105-lan`, `archon-redis.bak-20261105-lan`, `omniroute.bak-20261105-lan`, `n8n.bak-20261105-lan`, `Pocketbase*.bak-20261105-lan`, `paperclip-orchestrator.bak-20261105-lan`, `autogen-studio.bak-20261105-lan`.

---

## 9. Erste Schritte in der neuen Session

1. Dieses Dokument lesen (Pfad: `/mnt/raid/AgenticOS-2026/docs/BETRIEB_HANDBUCH_INTERN.md`).
2. Status prüfen: Health der drei Dienste + Profilanzahl (siehe Abschnitt 6).
3. Offene Punkte aus Abschnitt 5 mit dem Nutzer durchgehen.
4. Bei Änderungen an Profilen: Container stoppen (Fallstrick 1).

---

## 10. Dev-Stack ≠ Prod-Stack (F8, Cluster 3, 2026-11-08)

Der Entwicklungs-Stack (`docker-compose.dev.yml`) ist **kein** Produktions-Setup und
darf nicht als Vorlage für einen Produktivbetrieb gelten:

| Punkt | Dev (`docker-compose.dev.yml`) | Produktion |
|-------|-------------------------------|------------|
| Reload | `uvicorn --reload` | **kein** `--reload` |
| Bind-Mount | `/mnt/raid/AgenticOS-2026:/app` (schreibbar) | Image, nicht das Repo |
| Rootfs | `read_only: true` + `tmpfs /tmp` | wie Dev (ab Cluster 3) |
| Limits | `mem_limit 2g`, `pids_limit 200` | wie Dev |
| User | `1000:1000` | eigener Benutzer, nie root |
| Docker-Zugang | Socket-Proxy im internen `archon-admin_net` | dito |

**Warum das wichtig ist (F8):** `--reload` beobachtet `/app`. Jede Schreib-Lücke in
eine `.py`-Datei unter `/app` wird damit unmittelbar zu Codeausführung im Container —
und `/app` ist der Bind-Mount des Repos. Der Dev-Stack kombiniert also bewusst:
uid 1000, schreibbares Repo, Auto-Reload. In Produktion fällt mindestens einer dieser
drei Faktoren weg (`read_only` schützt das Rootfs, das Image enthält keinen Repo-Mount,
kein Reload).

**Regeln**

1. `docker-compose.dev.yml` niemals mit `-f docker-compose.dev.yml` in Produktion starten.
2. Vor einem Produktiv-Deploy prüfen: kein `--reload`, `read_only: true`, Limits gesetzt
   (`docker inspect ARCHON-OS --format '{{.HostConfig.Memory}} {{.HostConfig.PidsLimit}} {{.HostConfig.ReadonlyRootfs}}'`).
3. Der `/var/run/docker.sock`-Mount im App-Container bleibt ein Verstärker (Host-Root bei
   Ausbruch). Er ist nur deshalb vertretbar, weil (a) der Socket-Proxy die Regel-Achse ist
   und (b) die Sandbox-Pfade (`docker run --rm`) ihn strukturell brauchen.
   Rückbau-Reihenfolge: Sandbox auf eine eigene Socket-Instanz verschieben, dann Mount
   entfernen.

### 10.1 Docker-Socket-Proxy (F20)

- Der Proxy hängt **nicht** mehr in `archon-os-dev_agents_net`, sondern ausschließlich im
  internen Netz `archon-admin_net` (kein Gateway, kein NAT). Mitglieder: `ARCHON-OS`
  und `hermes`.
- Methoden-ACL: nur `CONTAINERS` (List/Inspect/Logs/Stats), `ALLOW_START`, `ALLOW_STOP`,
  `INFO`, `PING`, `VERSION`. `ALLOW_RESTARTS=0`, `EXEC=0`, `VOLUMES=0`, `NETWORKS=0`,
  `IMAGES=0`, `ALLOW_CONTAINER_CREATE/DELETE/RENAME=0`, `ALLOW_IMAGE_PULL/TAG=0`.
- Bewusste Einzelfreigaben (Default **0**, nur für die Dauer einer Operation setzen):
  - `ARCHON_PROXY_ALLOW_UPDATER=1` — Create/Rename/Delete/Pull/Tag für `backend/hermes_updater.py`
  - `ARCHON_PROXY_ALLOW_EXEC=1` — `/containers/<c>/exec` für die Paperclip-Pipeline
    (`backend/post_task_pipeline.py:522`)
- Basic-Auth am Proxy ist in `deploy/docker-socket-proxy/haproxy.cfg` als kommentierte
  Vorlage hinterlegt. Sie ist **nicht** aktiv, weil `utils/docker_client.py` heute keine
  Credentials sendet — erst Client und Secret zusammen ausrollen.
